from __future__ import annotations

from btc5m.book import TopOfBook
from btc5m.maker import MakerEngine, MakerState, Quote
from btc5m.markets import LiveMarket
from btc5m.strategy import StrategyState, decide
from btc5m.signal import BtcSignal
from conftest import make_cfg
import time

def _m():
    end=time.time()+25
    return LiveMarket('cid','slug','t','up','dn',end-300,end,.01,5,False,True)

def _sig(hold=.9):
    return BtcSignal(0,'test',100,130,30,'UP',2,True,8,130,8,30,hold,False,8,'UP')

def test_probability_gate_uses_net_ev(monkeypatch):
    # Exercise the existing empirical lead-table gate; the retired standalone
    # probability toggle is not a supported runtime strategy parameter.
    from types import SimpleNamespace
    cfg=make_cfg(delta_filter_enabled=False, lead_table_enabled=True, confirm_checks=1, min_net_edge=.02, max_entry_price=.90)
    monkeypatch.setattr('btc5m.strategy.hold_win_rate', lambda **kwargs: SimpleNamespace(hold_wr=.86))
    d=decide(cfg,_m(),TopOfBook(.8,20,.85,20),TopOfBook(.1,20,.99,20),_sig(.86),StrategyState(),already_in_market=False)
    assert d.action == 'SKIP'
    monkeypatch.setattr('btc5m.strategy.hold_win_rate', lambda **kwargs: SimpleNamespace(hold_wr=.95))
    d=decide(cfg,_m(),TopOfBook(.8,20,.85,20),TopOfBook(.1,20,.99,20),_sig(.95),StrategyState(),already_in_market=False)
    assert d.action == 'BUY' and d.net_edge is not None and d.net_edge > .02

def test_maker_fill_respects_queue_depth_and_cap(tmp_path):
    from btc5m.paper_queue import PaperQueue
    cfg = make_cfg(data_dir=tmp_path, maker_queue_factor=.25, maker_max_capital_usd=2.0)
    e = MakerEngine(cfg)
    m = _m()
    sid = e.store.open_maker_session(market_slug=m.market_slug, condition_id=m.condition_id,
                                     up_token=m.up_token, down_token=m.down_token, dry_run=True)
    now = time.time()
    book = TopOfBook(.50, 4, .51, 10)
    queue = PaperQueue('up', .50, 'BUY', now - 5)
    queue.observe_book(book, now - 5)
    st = MakerState(sid, m, quoting=True)
    st.quotes['UP'] = Quote('UP', 'up', .50, 10, now - 5, queue=queue)
    # Four displayed shares are ahead; ten opposing public shares consume
    # those four. Capital then caps the remaining six at four shares ($2).
    rows = [dict(timestamp=now - 1, size=10, asset='up', side='SELL', price=.50,
                 transactionHash='trade', conditionId=m.condition_id)]
    e.trade_tape.fetch = lambda *_: rows
    assert e._fill_side(st, 'UP', book, now)
    assert st.up_shares == 4.0
    assert st.up_cost == 2.0
    assert not e._fill_side(st, 'UP', book, now + .1)
    fill = e.store.conn.execute('select * from fills').fetchone()
    assert fill['execution_side'] == 'BUY'
    assert fill['price'] == .50 and fill['slippage_usd'] == 0


def test_maker_flatten_records_taker_fee(tmp_path):
    cfg=make_cfg(data_dir=tmp_path, maker_max_capital_usd=20.0)
    e=MakerEngine(cfg); m=_m(); sid=e.store.open_maker_session(market_slug=m.market_slug,condition_id=m.condition_id,up_token=m.up_token,down_token=m.down_token,dry_run=True)
    st=MakerState(sid,m,up_shares=10,up_cost=5,quoting=False); e._flatten_residual(st,TopOfBook(.40,3,.41,3),TopOfBook(.1,10,.2,10))
    row=e.store.conn.execute('select fee_usd,liquidity,strategy,size,execution_side,price,slippage_usd from fills').fetchone()
    assert row['size'] == 3 and row['liquidity'] == 'taker' and row['strategy'] == 'maker_flatten_taker' and row['fee_usd'] > 0

    assert row['execution_side'] == 'SELL' and row['price'] == .39
    assert abs(row['slippage_usd'] - .03) < 1e-9
    assert st.up_shares == 7 and not st.flattened
