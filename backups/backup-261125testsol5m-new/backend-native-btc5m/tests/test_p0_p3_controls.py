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

def test_probability_gate_uses_net_ev():
    cfg=make_cfg(probability_gate_enabled=True, delta_filter_enabled=False, lead_table_enabled=False, confirm_checks=1, min_net_edge=.02, max_entry_price=.90)
    d=decide(cfg,_m(),TopOfBook(.8,20,.85,20),TopOfBook(.1,20,.99,20),_sig(.86),StrategyState(),already_in_market=False)
    assert d.action == 'SKIP'
    d=decide(cfg,_m(),TopOfBook(.8,20,.85,20),TopOfBook(.1,20,.99,20),_sig(.95),StrategyState(),already_in_market=False)
    assert d.action == 'BUY' and d.net_edge is not None and d.net_edge > .02

def test_maker_fill_respects_queue_depth_and_cap(tmp_path):
    cfg=make_cfg(data_dir=tmp_path, maker_queue_factor=.25, maker_max_capital_usd=2.0)
    e=MakerEngine(cfg); m=_m(); sid=e.store.open_maker_session(market_slug=m.market_slug,condition_id=m.condition_id,up_token=m.up_token,down_token=m.down_token,dry_run=True)
    st=MakerState(sid,m,quoting=True); st.quotes['UP']=Quote('UP','up',.50,10,time.time()-20,time.time()-20)
    assert e._fill_side(st,'UP',TopOfBook(.50,4,.51,10),time.time()) is True
    assert st.up_shares <= 1.0 + 1e-9

def test_maker_flatten_records_taker_fee(tmp_path):
    cfg=make_cfg(data_dir=tmp_path, maker_max_capital_usd=20.0)
    e=MakerEngine(cfg); m=_m(); sid=e.store.open_maker_session(market_slug=m.market_slug,condition_id=m.condition_id,up_token=m.up_token,down_token=m.down_token,dry_run=True)
    st=MakerState(sid,m,up_shares=10,up_cost=5,quoting=False); e._flatten_residual(st,TopOfBook(.40,3,.41,3),TopOfBook(.1,10,.2,10))
    row=e.store.conn.execute('select fee_usd,liquidity,strategy,size from fills').fetchone()
    assert row['size'] == 3 and row['liquidity'] == 'taker' and row['strategy'] == 'maker_flatten_taker' and row['fee_usd'] > 0
