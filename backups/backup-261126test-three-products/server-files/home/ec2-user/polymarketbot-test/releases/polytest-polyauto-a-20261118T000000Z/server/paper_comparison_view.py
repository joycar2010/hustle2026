"""Read-only, experiment-owned Paper presentation. Never consult old ledgers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

BJ = timezone(timedelta(hours=8))


def primary_group():
    """The displayed Paper lane is operator-selectable, defaulting to A."""
    value = str(os.getenv('PAPER_PRIMARY_GROUP', 'BASELINE')).strip().upper()
    return value if value in {'BASELINE', 'FILTERED'} else 'BASELINE'


def experiment_root():
    return Path(os.environ['PAPER_COMPARISON_ROOT']).resolve()


def current_directory(root=None):
    root = Path(root or experiment_root()).resolve()
    current = json.loads((root/'current.json').read_text(encoding='utf-8'))
    directory = (root/current['directory']).resolve()
    if directory.parent != root/'runs':
        raise ValueError('Invalid experiment directory')
    return directory


def _lane_status(group):
    """Add an explicit status when a comparison lane has no fills.

    A zero PnL value is ambiguous in the UI: it can mean a genuine break-even
    result, or that the lane admitted no order at all.  The filtered/B lane is
    deliberately allowed to remain empty while its calibration and execution
    gates reject candidates.  Expose that distinction without changing the
    persisted ledger or manufacturing a fill.
    """
    group = group if isinstance(group, dict) else {}
    try:
        fills = int(group.get('fills') or 0)
    except (TypeError, ValueError):
        fills = 0
    try:
        candidates = int(group.get('candidates') or group.get('candidate_observations') or 0)
    except (TypeError, ValueError):
        candidates = 0
    try:
        accepted = int(group.get('accepted') or 0)
    except (TypeError, ValueError):
        accepted = 0
    blocked = group.get('blocked') if isinstance(group.get('blocked'), dict) else {}
    ranked_items = []
    for key, value in blocked.items():
        try:
            ranked_items.append((str(key), int(value or 0)))
        except (TypeError, ValueError):
            continue
    ranked = sorted(ranked_items, key=lambda item: item[1], reverse=True)
    if fills > 0:
        return {
            'trade_state': 'ACTIVE',
            'pnl_status': 'MEASURED',
            'pnl_is_zero_due_to_no_fill': False,
            'zero_pnl_reason': None,
        }
    reason = {
        'code': 'NO_FILLED_ORDERS' if candidates or accepted else 'NO_CANDIDATES',
        'candidates': candidates,
        'accepted': accepted,
        'blocked_reasons': [{'reason': key, 'count': count} for key, count in ranked[:8]],
    }
    return {
        'trade_state': 'NO_FILLED_ORDERS' if candidates or accepted else 'NO_CANDIDATES',
        'pnl_status': 'NOT_APPLICABLE',
        'pnl_is_zero_due_to_no_fill': True,
        'zero_pnl_reason': reason,
        'status_label_zh': '未成交（过滤/校准中）' if candidates or accepted else '等待候选',
    }


def read_summary(root=None, now=None):
    now = time.time() if now is None else now
    try:
        directory = current_directory(root)
        document = json.loads((directory/'summary.json').read_text(encoding='utf-8'))
        if document.get('mode') != 'paper' or document.get('live_trading_allowed') is not False:
            raise ValueError('Wrong experiment mode')
        stamp = float(document['updated_at'])
        if not math.isfinite(stamp):
            raise ValueError('Invalid timestamp')
        stopped=(document.get('health') or {}).get('runner_running') is False
        groups = {
            str(name): {**(value if isinstance(value, dict) else {}), **_lane_status(value)}
            for name, value in (document.get('groups') or {}).items()
        }
        document = {**document, 'groups': groups}
        return {**document, 'available':True, 'stale':stopped or not 0 <= now-stamp <= 10.,
                'age_sec':max(0.,now-stamp), 'primary_group':primary_group(),
                'source':'isolated_p3_public_paper', 'directory_name':directory.name}
    except (OSError, ValueError, TypeError, KeyError):
        return {'available':False, 'stale':True, 'mode':'paper', 'groups':{},
                'primary_group':primary_group(), 'reason':'PAPER_COMPARISON_NOT_READY',
                'source':'isolated_p3_public_paper'}


def read_runtime(root=None):
    document = read_summary(root)
    cfg = document.get('configuration') or {}
    pid = document.get('worker_pid')
    running = False
    if isinstance(pid,int) and pid > 1 and not document.get('stale'):
        try:
            args = (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
            running = any(a.endswith(b'/run_paper_p3.py') for a in args) and b'--live' not in args
        except OSError:
            pass
    return {'worker_running':running, 'worker_service_state':'RUNNING' if running else 'STOPPED',
            'worker_pid':pid if running else None, 'worker_config':cfg, 'effective_config':cfg,
            'configuration_sha256':document.get('config_sha256'),
            'effective_max_daily_loss_fraction':cfg.get('max_daily_loss_fraction'),
            'daily_loss_limit_source':'public_paper_config_manifest',
            'primary_group':primary_group(), 'mode':'paper', 'source':document['source']}


def account(document=None):
    document = read_summary() if document is None else document
    group_name=primary_group(); group = (document.get('groups') or {}).get(group_name) or {}
    day = datetime.now(BJ).strftime('%Y-%m-%d')
    daily = next((r for r in group.get('daily_rows',[]) if r.get('day') == day), {})
    positions=[]
    for row in group.get('positions',[]):
        q=float(row.get('quantity') or 0.)
        cost=float(row.get('cost_usd') or 0.)
        positions.append({**row,'asset':'BTC','condition_id':row['market_id'],
            'size':q,'remaining_size':q,'notional_usd':cost,
            'entry_price':cost/q if q else 0.,'dry_run':True,'source':document['source']})
    pnl={'realized_usd':daily.get('realized_usd',daily.get('realized_pnl_usd',0.)) if document.get('available') else None,
         'wins':daily.get('wins',0), 'losses':daily.get('losses',0), 'pending':len(positions),
         'fees_usd':daily.get('fees_usd',0.),'source':document['source']}
    item={**pnl,'open_value_usd':sum(p['notional_usd'] for p in positions)}
    return {'pnl':pnl,'positions':positions,'by_asset':{'BTC':item},'group':group_name,
            'open_value_usd':item['open_value_usd'],'source':document['source'],
            'available':document.get('available',False),'stale':document.get('stale',True)}


def daily_page(offset=0,limit=50,group=None):
    group = group or primary_group()
    document=read_summary(); data=(document.get('groups') or {}).get(group) or {}
    rows=[{**row,'realized_usd':row.get('realized_pnl_usd'),
           'economic_pnl_usd':row.get('net_pnl_usd'),
           'capital_base_usd':row.get('denominator_usd'),
           'taker_fees_usd':row.get('fees_usd'),'maker_fees_usd':0.,'rebates_usd':0.}
          for row in data.get('daily_rows') or []]
    return {'lane':'paper','asset':'BTC','group':group,'source':document['source'],
        'rows':rows[offset:offset+limit],'total_days':len(rows),'offset':offset,'limit':limit,
        'capital_base_usd':(document.get('configuration') or {}).get('capital_usd'),
        'trading_timezone':'Asia/Shanghai','available':document.get('available',False),
        'stale':document.get('stale',True),'updated_at':document.get('updated_at')}


def orders_page(offset=0,limit=20,start_ts=None,end_ts=None,group=None):
    group = group or primary_group()
    document=read_summary(); rows=[]; total=0; today_total=0
    start=datetime.now(BJ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    try:
        path=current_directory()/'comparison.sqlite3'
        with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True,timeout=.2)) as db:
            conditions=['lane=?']; params=[group]
            if start_ts is not None: conditions.append('ts>=?');params.append(start_ts)
            if end_ts is not None: conditions.append('ts<?');params.append(end_ts)
            where=' WHERE '+' AND '.join(conditions)
            total=db.execute('SELECT COUNT(*) FROM fills'+where,params).fetchone()[0]
            today_total=db.execute('SELECT COUNT(*) FROM fills'+where+' AND ts>=?',params+[start]).fetchone()[0]
            result=db.execute('SELECT fill_id,ts,market_id,payload FROM fills'+where+
                ' ORDER BY ts DESC,fill_id DESC LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
            markets={r[0]:json.loads(r[1]) for r in db.execute('SELECT market_id,payload FROM windows')}
        for fill_id,ts,market_id,payload in result:
            f=json.loads(payload);m=markets.get(market_id) or {};q=float(f.get('quantity',f.get('size',0.)))
            direction='UP' if f['token_id']==m.get('up_token') else 'DOWN'
            numeric_id=int(str(fill_id).rsplit('-',1)[-1])
            rows.append({**f,'id':numeric_id,'ts':ts,'asset':'BTC','condition_id':market_id,
                'market_slug':m.get('market_slug'),'size':q,'filled_size':q,
                'side':direction if f['side']=='BUY' else 'SELL_'+direction if f['side']=='SELL' else 'REDEEM',
                'action':f['side'],'status':'filled','dry_run':True,'source':document['source'],
                'record_key':'p3:'+group+':'+str(fill_id),'fee_usd':f.get('fee_usd'),
                'pnl_usd':f.get('realized_pnl_usd'),'settled':f['side']=='REDEEM',
                'result':('HIT' if f.get('price') == 1. else 'MISS') if f['side']=='REDEEM' else
                         'EXITED' if f['side']=='SELL' else 'PENDING'})
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        return {'rows':[],'total':0,'today_total':0,'available':False,'source':document['source'],
                'offset':offset,'limit':limit,'group':group,'lane':'paper'}
    return {'rows':rows,'total':total,'today_total':today_total,'offset':offset,'limit':limit,
            'group':group,'lane':'paper','source':document['source'],'available':document.get('available',False)}


def decisions(limit=50,since_id=0,group=None):
    group = group or primary_group()
    try:
        path=current_directory()/'comparison.sqlite3'
        with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True,timeout=.2)) as db:
            result=db.execute('SELECT id,ts,market_id,action,payload FROM decisions WHERE lane=? AND id>? ORDER BY id DESC LIMIT ?',
                              (group,since_id,limit)).fetchall()
            markets={r[0]:json.loads(r[1]) for r in db.execute('SELECT market_id,payload FROM windows')}
        rows=[]
        for ident,ts,market_id,action,payload in result:
            item=json.loads(payload);market=markets.get(market_id) or {}
            rows.append({'id':ident,'ts':ts,'asset':'BTC','condition_id':market_id,'market_slug':market.get('market_slug'),
                'side':item.get('side'),'action':action,'reason':', '.join(item.get('reasons') or [action]),
                'dry_run':True,'t_remaining':max(0.,float(market.get('end_ts') or ts)-ts),
                'ask_price':item.get('quote'),'ask_size':item.get('quantity'),'source':'isolated_p3_public_paper'})
        return rows
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        return []


def counts(group=None):
    group = group or primary_group()
    start=datetime.now(BJ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    result={'decisions':0,'orders':0,'today_decisions':0,'today_orders':0,'since':start}
    try:
        path=current_directory()/'comparison.sqlite3'
        with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True,timeout=.2)) as db:
            for table,key in (('decisions','decisions'),('fills','orders')):
                result[key]=db.execute('SELECT COUNT(*) FROM '+table+' WHERE lane=?',(group,)).fetchone()[0]
                result['today_'+key]=db.execute('SELECT COUNT(*) FROM '+table+' WHERE lane=? AND ts>=?',(group,start)).fetchone()[0]
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):pass
    return result


def export_public_config(values, destination=None):
    """Copy only numeric public strategy fields. No dotenv passes the boundary."""
    from bot.paper_comparison import PaperComparisonConfig, atomic_json
    from dataclasses import asdict
    cfg=asdict(PaperComparisonConfig())
    names={
        'min_entry_price':'MIN_ENTRY_PRICE','max_entry_price':'MAX_ENTRY_PRICE',
        'seconds_before_close':'SECONDS_BEFORE_CLOSE','min_t_remaining_sec':'MIN_T_REMAINING_SEC',
        'btc_up_min_delta_usd':'BTC_UP_MIN_DELTA_USD','btc_down_max_delta_usd':'BTC_DOWN_MAX_DELTA_USD',
        'confirm_checks':'CONFIRM_CHECKS','order_risk_fraction':'ORDER_RISK_FRACTION',
        'max_open_positions':'MAX_OPEN_POSITIONS','max_daily_loss_fraction':'MAX_DAILY_LOSS_FRACTION',
        'max_daily_realized_profit_fraction':'MAX_DAILY_REALIZED_PROFIT_FRACTION',
        'reversal_held_bid_drawdown':'REVERSAL_HELD_BID_DRAWDOWN',
        'reversal_confirm_checks':'REVERSAL_CONFIRM_CHECKS','reversal_exit_window_sec':'REVERSAL_EXIT_WINDOW_SEC',
        'entry_maker_ttl_sec':'ENTRY_MAKER_TTL_SEC','profit_maker_ttl_sec':'PROFIT_MAKER_TTL_SEC',
        'profit_target_fraction':'PROFIT_TARGET_FRACTION','profit_target_ticks':'PROFIT_TARGET_TICKS',
        'near_close_exit_window_sec':'NEAR_CLOSE_EXIT_WINDOW_SEC',
    }
    for field,name in names.items():
        if name in values and str(values[name]).strip():
            raw=float(values[name]);cfg[field]=int(raw) if isinstance(cfg[field],int) else raw
    validated=PaperComparisonConfig(**cfg);validated.validate()
    if destination is not None:
        atomic_json(destination,cfg)
    return cfg
