"""CrossArb P1 真金 CANARY —— 强制执行一笔最小名义额($64),验证全链路两腿真成交。

目的:测 P0 永远测不到的变量 —— 看到价 → 两腿真成交的兑现率、实际滑移、复核/止损逻辑。
强制单笔(不等 net>25bps 机会),接受这笔大概率小亏(吃点差+gas)。但保留全部安全护栏:
  - 链上买入用回执 Transfer 事件实测到账(非余额差);nonce 显式递增;PendingTxError 停机
  - 偏离报价>3% 拒绝;做空后取整差额自动卖回;币安时钟同步
  - 执行前设亏损闸:paper net < LOSS_FLOOR_BPS 时拒绝(防极端不利时白亏)
只跑一次就退出。用法: PYTHONUTF8=1 python3 canary.py [--yes]
"""
import sys
import time
from decimal import Decimal

sys.path.insert(0, '.')
from app.config import cfg
from app.markets import load_markets
from app.onchain_exec import OnchainExec
from app.binance_exec import BinanceExec, FUTURES_LIVE, FUTURES_TESTNET
from app.spread_calc import compute_spread
from app.chains import chain_of
from app.chain_rpc import PendingTxError

NOTIONAL = 64.0           # 币安 BTCUSDT 最小名义额 $50,0.001 BTC≈$64
LOSS_FLOOR_BPS = -80.0    # 亏损闸:paper net 低于此拒绝执行(防极端不利白亏)


def main():
    confirmed = "--yes" in sys.argv
    m = {x.key: x for x in load_markets()}.get(cfg.exec_market)
    if m is None:
        print(f"市场 {cfg.exec_market} 不存在"); return
    if cfg.exec_mode == "dry-run":
        print("⚠ 当前 mode=dry-run,canary 不会下真单(仅演练打印)。要真金请设 CROSSARB_EXEC_MODE=live")
    print(f"=== CANARY mode={cfg.exec_mode} market={m.key} 名义=${NOTIONAL} ===")

    bn = BinanceExec(cfg.bn_api_key, cfg.bn_api_secret,
                     FUTURES_TESTNET if cfg.exec_mode == "testnet" else FUTURES_LIVE)
    dual = False
    if cfg.exec_mode in ("testnet", "live"):
        bn.sync_time()
        dual = bn.position_mode_dual()
        print(f"    持仓模式: {'双向(带positionSide)' if dual else '单向'}")
    oc = OnchainExec(cfg.exec_mode, cfg.exec_wallet_addr, cfg.exec_kms_key_id, cfg.kyber_client_id,
                     rpc_url=cfg.exec_rpc, kms_region=cfg.exec_kms_region,
                     slippage_bps=cfg.exec_slippage_bps, approve_cap_usd=cfg.exec_approve_cap_usd,
                     recv_timeout=cfg.exec_recv_timeout_sec)

    # ① 报价 + 计算 paper net
    print("[1] 取链上报价 + 币安行情...")
    q = oc.quote_buy(m, NOTIONAL)
    bt = bn.book_ticker(m.binance_symbol)
    ch = chain_of(m.chain)
    paper = compute_spread(
        market=m.key, binance_symbol=m.binance_symbol, ts=int(time.time()*1000),
        dex_eff_price=q.eff_price, dex_mid_price=q.mid_price, base_out=q.base_out,
        slippage_bps=q.slippage_bps, gas_usd=(q.gas_usd or 0.01),
        fut_bid=float(bt["bid"]), fut_ask=float(bt["ask"]), notional_usd=NOTIONAL,
        taker_fee_bps=cfg.taker_fee_bps, recycle_bps=ch.recycle_bps,
        min_net_bps=cfg.exec_min_net_bps, exit_floor_bps=cfg.exit_floor_bps)
    print(f"    DEX eff={q.eff_price:.2f} 买到 {q.base_out:.6f} BTC | 币安 bid={bt['bid']}")
    print(f"    paper: gross={paper.gross_bps:.2f}bps net={paper.net_bps:.2f}bps")

    # ② 亏损闸
    if paper.net_bps < LOSS_FLOOR_BPS:
        print(f"✗ paper net {paper.net_bps:.2f} < 亏损闸 {LOSS_FLOOR_BPS}bps,拒绝执行(此刻太不利,稍后再试)")
        return
    print(f"    ✓ 过亏损闸({LOSS_FLOOR_BPS}bps)")

    # ③ 最终人工确认
    if cfg.exec_mode == "live" and not confirmed:
        print(f"\n⚠⚠ 即将用真金执行:链上买 ${NOTIONAL} BTC + 币安做空 0.001 BTC")
        print("   确认无误请加 --yes 重跑: PYTHONUTF8=1 python3 canary.py --yes")
        return

    # ④ 链上买入腿
    print("[2] 链上买入腿...")
    t0 = time.time()
    try:
        buy = oc.execute_buy(m, NOTIONAL, q)
    except PendingTxError as pe:
        print(f"✗✗ 链上买入状态未知(已广播未确认),停机待人工核对链上: {pe}")
        return
    except Exception as e:
        print(f"✗ 链上买入失败: {type(e).__name__}: {e}")
        return
    base_out = buy.get("base_out") or q.base_out
    print(f"    {'✓ 成交' if buy.get('executed') else '(未上链)'} base_out={base_out:.8f} "
          f"eff={buy.get('eff_price'):.2f} tx={buy.get('tx_hash')} 耗时{time.time()-t0:.1f}s")

    # ⑤ 币安做空腿
    print("[3] 币安做空腿...")
    qty = bn.round_qty(m.binance_symbol, Decimal(str(base_out)))
    print(f"    做空数量(取整后): {qty} BTC")
    if cfg.exec_mode == "dry-run":
        print("    dry-run: 不真下单"); return
    if qty <= 0:
        print("    ✗ 取整后数量为0,跳过"); return
    coid = f"canary{int(t0*1000)}"
    try:
        resp = bn.futures_market_short(m.binance_symbol, qty, coid, dual=dual)
        ap = resp.get("avgPrice"); eq = resp.get("executedQty")
        print(f"    ✓ 做空成交 qty={eq} avgPrice={ap} status={resp.get('status')}")
    except Exception as e:
        print(f"    ✗ 做空失败(裸多!): {type(e).__name__}: {e}")
        print("    → 复核真实状态...")
        try:
            o = bn.get_order_by_client_id(m.binance_symbol, coid)
            print(f"    复核: status={o.get('status')} executedQty={o.get('executedQty')}")
            if o.get("status") == "FILLED":
                print("    实际已成交,无需卖回"); return
        except Exception as e2:
            print(f"    复核也失败: {e2}")
        print("    → 卖回链上 BTC 止损...")
        try:
            sb = oc.sell_back(m, base_out)
            print(f"    卖回: {sb}")
        except Exception as e3:
            print(f"    ✗✗ 卖回失败,手动处理裸多! base_out={base_out}: {e3}")
        return

    # ⑥ 取整差额(裸多)清理
    naked = base_out - float(eq or qty)
    if naked > 0.0001:
        print(f"[4] 取整差额裸多 {naked:.6f} BTC,卖回...")
        try:
            sb = oc.sell_back(m, naked)
            print(f"    卖回差额: {sb}")
        except Exception as e:
            print(f"    差额卖回失败(小额,可手动): {e}")

    print("\n✅ CANARY 完成!两腿全成交。请核对:")
    print(f"   链上买入 tx: {buy.get('tx_hash')}")
    print(f"   币安做空 avgPrice={ap}  数量={eq}")
    print(f"   paper net 当时 = {paper.net_bps:.2f}bps")


if __name__ == "__main__":
    main()
