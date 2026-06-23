"""两腿协调器 + 执行可捕获率埋点(P1 验证核心)。

目的:测出"看到机会 → 两腿真正成交"的真实兑现率与滑移 —— P0 永远测不到、却决定策略生死的变量。
顺序反转:先确认链上买入成交 → 再用确定数量去币安做空(避免先开空后链上失败=裸空)。
三档安全:dry-run(都不真做,只记应做)/ testnet(币安测试网真做空+链上仅报价)/ live(真金)。
每次尝试落 exec_log.csv:各阶段时间戳 + 报价vs实际成交价 + 纸面net vs 兑现net。
"""
from __future__ import annotations

import csv
import os
import threading
import time
from decimal import Decimal

from .binance_exec import FUTURES_LIVE, FUTURES_TESTNET, BinanceExec
from .chain_rpc import PendingTxError
from .config import cfg
from .markets import load_markets
from .onchain_exec import OnchainExec
from .spread_calc import compute_spread
from .chains import chain_of

EXEC_LOG_COLS = [
    "ts_seen", "market", "binance_symbol", "mode", "notional_usd",
    "paper_gross_bps", "paper_net_bps", "decision",
    "buy_executed", "buy_eff_price", "buy_base_out", "ms_to_buy",
    "short_executed", "short_qty", "short_avg_price", "ms_to_short",
    "realized_net_bps", "capture_ratio", "outcome", "note",
]


class ExecCoordinator(threading.Thread):
    def __init__(self, log_path: str = "./data/exec_log.csv"):
        super().__init__(daemon=True)
        self.mode = cfg.exec_mode
        self.log_path = log_path
        markets = {m.key: m for m in load_markets()}
        self.market = markets.get(cfg.exec_market)
        base = FUTURES_TESTNET if self.mode == "testnet" else FUTURES_LIVE
        self.bn = BinanceExec(cfg.bn_api_key, cfg.bn_api_secret, base_url=base)
        if self.mode in ("testnet", "live"):
            self.bn.sync_time()  # 同步币安时钟,防 -1021
        self.onchain = OnchainExec(
            self.mode, cfg.exec_wallet_addr, cfg.exec_kms_key_id, cfg.kyber_client_id,
            rpc_url=cfg.exec_rpc, kms_region=cfg.exec_kms_region, slippage_bps=cfg.exec_slippage_bps,
            approve_cap_usd=cfg.exec_approve_cap_usd, recv_timeout=cfg.exec_recv_timeout_sec)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # 熔断计数
        self.trades = 0
        self.daily_spend = 0.0
        self.consec_loss = 0
        self._init_log()

    def _init_log(self):
        d = os.path.dirname(self.log_path)
        if d:
            os.makedirs(d, exist_ok=True)
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(EXEC_LOG_COLS)

    def _log(self, row: dict):
        with self._lock:
            with open(self.log_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([row.get(c, "") for c in EXEC_LOG_COLS])

    def stop(self):
        self._stop.set()

    def _circuit_ok(self) -> tuple[bool, str]:
        if self.market is None:
            return False, f"市场 {cfg.exec_market} 不存在"
        if self.trades >= cfg.exec_max_trades:
            return False, f"达单数上限 {cfg.exec_max_trades}"
        if self.daily_spend >= cfg.exec_max_daily_usd:
            return False, f"达单日支出上限 ${cfg.exec_max_daily_usd}"
        if self.consec_loss >= 5:
            return False, "连亏5笔,熔断"
        return True, ""

    def _attempt(self, m, q, bt, paper):
        """执行一次套利尝试(顺序:链上买入 → 币安做空),记录全程时间戳与成交价。"""
        notional = cfg.exec_notional_usd
        t0 = time.time()
        out = {"ts_seen": int(t0 * 1000), "market": m.key, "binance_symbol": m.binance_symbol,
               "mode": self.mode, "notional_usd": notional,
               "paper_gross_bps": round(paper.gross_bps, 2), "paper_net_bps": round(paper.net_bps, 2),
               "decision": "EXECUTE"}
        # ① 链上买入腿
        try:
            buy = self.onchain.execute_buy(m, notional, q)
        except PendingTxError as pe:
            # swap 已广播但超时未确认 —— 状态未知!绝不能继续做空(可能已买入也可能没),
            # 也绝不能重发(防双花)。记 HALT 并熔断停机,等人工核对链上后再启。
            out.update(outcome="BUY_PENDING_HALT",
                       note=f"链上买入状态未知,已停机待人工核对: {pe}")
            self._log(out)
            self._stop.set()  # 触发停机,防止带着未知敞口继续
            return
        except Exception as e:  # noqa: BLE001
            out.update(outcome="BUY_FAIL", note=f"{type(e).__name__}: {e}")
            self._log(out); return
        buy_price = buy.get("eff_price") or q.eff_price
        base_out = buy.get("base_out") or q.base_out
        t_buy = time.time()
        out.update(buy_executed=int(buy.get("executed", False)), buy_eff_price=round(buy_price, 6),
                   buy_base_out=round(base_out, 8), ms_to_buy=int((t_buy - t0) * 1000))
        if self.mode == "live":
            self.daily_spend += notional
        # ② 币安做空腿(testnet/live 真下;dry-run 用 bid 作参考价)
        qty = self.bn.round_qty(m.binance_symbol, Decimal(str(base_out)))
        short_price = float(bt["bid"]); short_exec = 0; actual_short_qty = 0.0
        if self.mode in ("testnet", "live") and qty > 0:
            try:
                coid = f"cax{int(t0*1000)}"
                resp = self.bn.futures_market_short(m.binance_symbol, qty, coid)
                ap = resp.get("avgPrice") or resp.get("avgprice")
                short_price = float(ap) if ap and float(ap) > 0 else short_price
                actual_short_qty = float(resp.get("executedQty", 0) or qty)
                short_exec = 1
            except Exception as e:  # noqa: BLE001
                # 响应丢失(超时/5xx)时订单可能已成交!先复核真实状态,防误判致裸空
                verified_qty = 0.0
                try:
                    order = self.bn.get_order_by_client_id(m.binance_symbol, coid)
                    if order.get("status") == "FILLED":
                        verified_qty = float(order.get("executedQty", 0))
                        ap = order.get("avgPrice")
                        if verified_qty > 0:
                            short_price = float(ap) if ap and float(ap) > 0 else short_price
                            actual_short_qty = verified_qty
                            short_exec = 1
                            out["note"] = f"做空响应丢失但复核已成交 qty={verified_qty}"
                except Exception:  # noqa: BLE001
                    pass  # 复核也失败,按未成交处理
                if short_exec == 0:
                    # 确认未成交 → 裸多敞口!live 须立即卖回止损
                    out.update(short_executed=0, outcome="SHORT_FAIL_NAKED",
                               note=f"做空失败(裸腿!): {type(e).__name__}: {e}")
                    if self.mode == "live":
                        try:
                            self.onchain.sell_back(m, base_out)
                            out["note"] += " | 已卖回止损"
                        except Exception as e2:  # noqa: BLE001
                            out["note"] += f" | 卖回也失败: {e2}"
                    self._log(out); self.trades += 1; self.consec_loss += 1; return
            # 做空成功,检查取整差异(ROUND_DOWN 可能致裸多累积)
            naked_long = base_out - actual_short_qty
            if self.mode == "live" and naked_long > 0.0001:  # 阈值 0.0001 BTC ≈ $6
                try:
                    self.onchain.sell_back(m, naked_long)
                    out["note"] = (out.get("note", "") + f" | 取整差额{naked_long:.6f}已卖回").strip()
                except Exception as e3:  # noqa: BLE001
                    out["note"] = (out.get("note", "") + f" | 取整差额{naked_long:.6f}卖回失败: {e3}").strip()
        t_short = time.time()
        # ③ 兑现 net:做空价 vs 实际买价(扣双边taker+双向gas+退出+recycle 用同口径)
        ch = chain_of(m.chain)
        realized = compute_spread(
            market=m.key, binance_symbol=m.binance_symbol, ts=int(t_short * 1000),
            dex_eff_price=buy_price, dex_mid_price=q.mid_price, base_out=base_out,
            slippage_bps=q.slippage_bps, gas_usd=(q.gas_usd or 0.01),
            fut_bid=short_price, fut_ask=float(bt["ask"]), notional_usd=notional,
            taker_fee_bps=cfg.taker_fee_bps, recycle_bps=ch.recycle_bps,
            min_net_bps=cfg.exec_min_net_bps, exit_floor_bps=cfg.exit_floor_bps,
        )
        cap = (realized.net_bps / paper.net_bps) if paper.net_bps else 0.0
        out.update(short_executed=short_exec, short_qty=float(qty), short_avg_price=round(short_price, 6),
                   ms_to_short=int((t_short - t_buy) * 1000),
                   realized_net_bps=round(realized.net_bps, 2), capture_ratio=round(cap, 3),
                   outcome="OK", note="dry-run参考价" if self.mode == "dry-run" else "")
        self._log(out)
        self.trades += 1
        self.consec_loss = self.consec_loss + 1 if realized.net_bps < 0 else 0

    def run(self):
        if self.market is None:
            self._log({"ts_seen": int(time.time()*1000), "outcome": "NO_MARKET",
                       "note": f"{cfg.exec_market} 未配置"})
            return
        m = self.market
        while not self._stop.is_set():
            t0 = time.time()
            try:
                q = self.onchain.quote_buy(m, cfg.exec_notional_usd)
                bt = self.bn.book_ticker(m.binance_symbol)
                ch = chain_of(m.chain)
                paper = compute_spread(
                    market=m.key, binance_symbol=m.binance_symbol, ts=int(t0*1000),
                    dex_eff_price=q.eff_price, dex_mid_price=q.mid_price, base_out=q.base_out,
                    slippage_bps=q.slippage_bps, gas_usd=(q.gas_usd or 0.01),
                    fut_bid=float(bt["bid"]), fut_ask=float(bt["ask"]), notional_usd=cfg.exec_notional_usd,
                    taker_fee_bps=cfg.taker_fee_bps, recycle_bps=ch.recycle_bps,
                    min_net_bps=cfg.exec_min_net_bps, exit_floor_bps=cfg.exit_floor_bps,
                )
                if paper.net_bps > cfg.exec_min_net_bps:
                    ok, why = self._circuit_ok()
                    if ok:
                        self._attempt(m, q, bt, paper)
                    else:
                        self._log({"ts_seen": int(t0*1000), "market": m.key, "mode": self.mode,
                                   "paper_net_bps": round(paper.net_bps, 2), "decision": "SKIP_CIRCUIT",
                                   "outcome": "SKIP", "note": why})
            except Exception as e:  # noqa: BLE001
                self._log({"ts_seen": int(t0*1000), "market": cfg.exec_market, "mode": self.mode,
                           "outcome": "TICK_ERR", "note": f"{type(e).__name__}: {e}"})
            self._stop.wait(max(0.0, cfg.exec_poll_sec - (time.time() - t0)))


def main():
    """独立进程入口:python -m app.coordinator"""
    import logging
    logging.basicConfig(level=logging.INFO)
    print(f"[exec] 启动协调器 mode={cfg.exec_mode} market={cfg.exec_market} notional=${cfg.exec_notional_usd} "
          f"触发net>{cfg.exec_min_net_bps}bps")
    if cfg.exec_mode == "live":
        print("[exec] ⚠ LIVE 模式:真金!需 KMS+钱包+独立币安账户。")
    c = ExecCoordinator()
    c.start()
    try:
        while c.is_alive():
            c.join(1)
    except KeyboardInterrupt:
        c.stop()


if __name__ == "__main__":
    main()
