"""CrossArb P1 CANARY 平仓 —— 对称平掉 canary 开的对冲仓(链上卖回 WBTC + 币安平空头)。

验证"开+平"完整生命周期:确认平仓也能两腿干净退出。
顺序:先平币安空头(交易所撤仓即时确定)→ 再链上卖回 WBTC(避免先卖链上后平币安失败=裸空)。
  —— 与开仓顺序相反:开仓先链上(防先空后买失败裸空),平仓先币安(防先卖链上后平空失败裸空)。
保留全护栏:双向模式适配、回执 Transfer 实测、PendingTxError 停机。
用法: PYTHONUTF8=1 python3 canary_close.py [--yes]
"""
import sys
import time
from decimal import Decimal

sys.path.insert(0, '.')
from app.config import cfg
from app.markets import load_markets
from app.onchain_exec import OnchainExec
from app.binance_exec import BinanceExec, FUTURES_LIVE, FUTURES_TESTNET
from app.chains import chain_of
from app.chain_rpc import ChainRpc, PendingTxError


def main():
    confirmed = "--yes" in sys.argv
    m = {x.key: x for x in load_markets()}.get(cfg.exec_market)
    if m is None:
        print(f"市场 {cfg.exec_market} 不存在"); return
    ch = chain_of(m.chain)
    WBTC = m.base_token
    print(f"=== CANARY 平仓 mode={cfg.exec_mode} market={m.key} ===")

    bn = BinanceExec(cfg.bn_api_key, cfg.bn_api_secret,
                     FUTURES_TESTNET if cfg.exec_mode == "testnet" else FUTURES_LIVE)
    dual = False
    if cfg.exec_mode in ("testnet", "live"):
        bn.sync_time()
        dual = bn.position_mode_dual()
    oc = OnchainExec(cfg.exec_mode, cfg.exec_wallet_addr, cfg.exec_kms_key_id, cfg.kyber_client_id,
                     rpc_url=cfg.exec_rpc, kms_region=cfg.exec_kms_region,
                     slippage_bps=cfg.exec_slippage_bps, approve_cap_usd=cfg.exec_approve_cap_usd,
                     recv_timeout=cfg.exec_recv_timeout_sec)

    # ① 读当前两腿持仓
    print("[1] 读当前两腿持仓...")
    rpc = ChainRpc(cfg.exec_rpc, ch.chain_id)
    wbtc_raw = rpc.erc20_balance(WBTC, cfg.exec_wallet_addr)
    wbtc_qty = wbtc_raw / (10 ** m.base_decimals)
    short_amt = 0.0
    for p in bn._request("GET", "/fapi/v2/positionRisk", {"symbol": m.binance_symbol}):
        a = float(p.get("positionAmt", 0))
        if a != 0:
            short_amt = a
            print(f"    币安 {p.get('positionSide')}: {a} BTC @ entry {p.get('entryPrice')}")
    print(f"    链上 WBTC: {wbtc_qty:.8f}")
    if wbtc_qty <= 0 and short_amt == 0:
        print("    两腿都已为空,无需平仓"); return

    if cfg.exec_mode == "live" and not confirmed:
        print(f"\n⚠ 即将平仓:币安买回平空 {abs(short_amt)} BTC + 链上卖回 {wbtc_qty:.6f} WBTC")
        print("   确认请加 --yes: PYTHONUTF8=1 python3 canary_close.py --yes")
        return

    # ② 先平币安空头(BUY 平 SHORT)
    if cfg.exec_mode in ("testnet", "live") and short_amt < 0:
        print("[2] 币安平空头(BUY)...")
        close_qty = bn.round_qty(m.binance_symbol, Decimal(str(abs(short_amt))))
        try:
            resp = bn.futures_close_short(m.binance_symbol, close_qty, dual=dual)
            print(f"    ✓ 平空成交 qty={resp.get('executedQty')} avgPrice={resp.get('avgPrice')} status={resp.get('status')}")
        except Exception as e:
            print(f"    ✗ 平空失败,中止(勿继续卖链上,否则裸空): {type(e).__name__}: {e}")
            return
    elif cfg.exec_mode == "dry-run":
        print("[2] dry-run: 不真平币安")

    # ③ 链上卖回 WBTC → USDC
    if wbtc_qty > 0:
        print("[3] 链上卖回 WBTC → USDC...")
        try:
            sb = oc.sell_back(m, wbtc_qty)
            print(f"    {'✓ 卖回' if sb.get('executed') else '(未上链)'} "
                  f"usdc_out={sb.get('usdc_out')} tx={sb.get('tx_hash')}")
        except PendingTxError as pe:
            print(f"    ✗✗ 卖回状态未知(已广播未确认),停机待人工核对: {pe}")
            return
        except Exception as e:
            print(f"    ✗ 卖回失败(币安已平,链上仍持多头,手动处理!): {type(e).__name__}: {e}")
            return

    print("\n✅ 平仓完成。开+平完整生命周期验证通过。")


if __name__ == "__main__":
    main()
