"""每日对账+汇总,推飞书。systemd timer 触发: python3 daily_recon.py
按 cfg.exec_market 自适应(不写死OP/WBTC/BTCUSDT) —— 切BSC:CAKE等市场自动跟随。"""
import sys, csv, time; sys.path.insert(0,'.')
from datetime import datetime, timezone, timedelta
from app.chain_rpc import ChainRpc
from app.chains import chain_of
from app.markets import load_markets
from app.binance_exec import BinanceExec, FUTURES_LIVE
from app.config import cfg
from app.feishu_daily import send_text, resolve_open_id_by_mobile

m={x.key:x for x in load_markets()}.get(cfg.exec_market)
ch=chain_of(m.chain) if m else chain_of('OP')
base_sym=cfg.exec_market.split(':')[-1] if ':' in cfg.exec_market else 'BASE'
rpc=ChainRpc(cfg.exec_rpc,ch.chain_id)
W=cfg.exec_wallet_addr
base_bal=rpc.erc20_balance(m.base_token,W)/(10**m.base_decimals) if m else 0.0
stable=rpc.erc20_balance(ch.stable,W)/(10**ch.stable_decimals); native=rpc.eth_balance(W)/1e18
bn=BinanceExec(cfg.bn_api_key,cfg.bn_api_secret,FUTURES_LIVE); bn.sync_time()
sym=m.binance_symbol if m else 'BTCUSDT'
pos=[p for p in bn._request('GET','/fapi/v2/positionRisk',{'symbol':sym}) if float(p.get('positionAmt',0))!=0]
short_amt=abs(float(pos[0]['positionAmt'])) if pos else 0.0
# 两腿匹配检查(容差按 base 量级,CAKE整数级用1,BTC小数级用0.0005)
tol=1.0 if base_bal>10 else 0.0005
mismatch = abs(base_bal - short_amt) > tol and (base_bal>0 or short_amt>0)
# 当日 exec_log 统计
today=datetime.now(timezone.utc).strftime('%Y-%m-%d')
ok=naked=halt=0; caps=[]; nets=[]
try:
    for r in csv.DictReader(open('data/exec_log.csv',encoding='utf-8')):
        try: day=datetime.fromtimestamp(int(r['ts_seen'])/1000,timezone.utc).strftime('%Y-%m-%d')
        except: continue
        if day!=today: continue
        o=r.get('outcome','')
        if o=='OK':
            ok+=1
            try: caps.append(float(r.get('capture_ratio') or 0)); nets.append(float(r.get('realized_net_bps') or 0))
            except: pass
        elif o=='SHORT_FAIL_NAKED': naked+=1
        elif 'HALT' in o: halt+=1
except FileNotFoundError: pass
avg_cap=sum(caps)/len(caps) if caps else 0
avg_net=sum(nets)/len(nets) if nets else 0
bj=(datetime.now(timezone.utc)+timedelta(hours=8)).strftime('%m-%d %H:%M')
L=[f'📋 CrossArb P1 日报 {bj}(北京)',f'市场 {cfg.exec_market} 触发net>{cfg.exec_min_net_bps:g}bps','',
   f'【持仓对账】{"⚠不匹配!" if mismatch else "✓两腿匹配/无持仓"}',
   f'· 链上{base_sym} {base_bal:.4f} | 币安空头 {short_amt:.4f}',
   f'· 稳定币 {stable:.2f} | gas {native:.5f}',
   '',
   f'【今日成交】',
   f'· 成交 {ok} 笔 | 裸腿 {naked} | 停机 {halt}',
   (f'· 平均兑现net {avg_net:.1f}bps | 平均捕获率 {avg_cap*100:.0f}%' if ok else f'· 今日暂无成交(基差未达{cfg.exec_min_net_bps:g}bps)')]
if native<0.002: L.append('⚠ gas余额偏低,需补')
text='\n'.join(L)
# 发飞书(mobile优先,绕开跨应用open_id)
aid,sec=cfg.feishu_app_id,cfg.feishu_app_secret
if cfg.feishu_mobile:
    oid,_=resolve_open_id_by_mobile(aid,sec,cfg.feishu_mobile); rtype,rid=("open_id",oid) if oid else (None,None)
elif cfg.feishu_email: rtype,rid="email",cfg.feishu_email
elif cfg.feishu_open_id: rtype,rid='open_id',cfg.feishu_open_id
else: rtype,rid=None,None
if rtype:
    ok2,d=send_text(aid,sec,rtype,rid,text); print('飞书:', 'OK' if ok2 else d)
print(text)
