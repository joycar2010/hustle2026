"""P1 真金执行监控数据聚合 —— 只读,绝不触碰 coordinator 进程/交易状态。

数据源:
- data/exec_log.csv(P1 每笔成交一行,coordinator 写,这里只读)
- 链上 RPC(钱包实时 WBTC/USDC/ETH 余额)
- 币安 API(实时持仓 + 当前基差报价)
所有查询有超时与异常兜底,任一失败不影响其他区块(面板局部降级而非整体崩)。
不读 .env 里的 secret 到前端;链上/币安查询在后端完成,前端只拿聚合结果。
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone, timedelta

from .config import cfg
from .chains import chain_of

# 拆分缓存:基差轻(KyberSwap+币安~150ms)要实时→1.5s;余额持仓重、变化慢→8s
_SPREAD_CACHE: dict = {"ts": 0.0, "data": None}
_SPREAD_TTL = 1.5
_BAL_CACHE: dict = {"ts": 0.0, "data": None}
_BAL_TTL = 8.0


def _market_ctx():
    """按当前 cfg.exec_market 取链上下文(market对象/链/base_token/RPC/币安symbol),
    不再写死 OP:BTC —— 切 BSC:CAKE 等市场时面板/对账自动跟随。"""
    from .markets import load_markets
    m = {x.key: x for x in load_markets()}.get(cfg.exec_market)
    ch = chain_of(m.chain) if m else chain_of("OP")
    return m, ch



def _read_exec_rows() -> list[dict]:
    """读 exec_log.csv。容忍缺表头(老文件无表头)——用 EXEC_LOG_COLS 固定列序解析。"""
    from .coordinator import EXEC_LOG_COLS
    path = "./data/exec_log.csv"
    try:
        with open(path, newline="", encoding="utf-8") as f:
            raw = list(csv.reader(f))
    except FileNotFoundError:
        return []
    if not raw:
        return []
    rows = []
    # 若首行第一格是表头名(非数字时间戳),跳过它
    start = 1 if raw[0] and raw[0][0] == "ts_seen" else 0
    for cells in raw[start:]:
        if not cells or len(cells) < len(EXEC_LOG_COLS):
            continue
        rows.append({EXEC_LOG_COLS[i]: cells[i] for i in range(len(EXEC_LOG_COLS))})
    return rows


def _f(v, d=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return d


def _summary(rows: list[dict]) -> dict:
    """聚合统计:累计/今日 成交、捕获率、兑现net分布、盈亏估算。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tot = {"trades": 0, "ok": 0, "naked": 0, "halt": 0, "caps": [], "nets": [], "papers": []}
    tod = {"trades": 0, "ok": 0, "naked": 0}
    for r in rows:
        oc = r.get("outcome", "")
        try:
            day = datetime.fromtimestamp(int(r["ts_seen"]) / 1000, timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, TypeError, KeyError):
            day = ""
        is_today = day == today
        if oc == "OK":
            tot["ok"] += 1; tot["trades"] += 1
            tot["caps"].append(_f(r.get("capture_ratio")))
            tot["nets"].append(_f(r.get("realized_net_bps")))
            tot["papers"].append(_f(r.get("paper_net_bps")))
            if is_today:
                tod["ok"] += 1; tod["trades"] += 1
        elif oc == "SHORT_FAIL_NAKED":
            tot["naked"] += 1; tot["trades"] += 1
            if is_today:
                tod["naked"] += 1; tod["trades"] += 1
        elif "HALT" in oc:
            tot["halt"] += 1

    def avg(a):
        return round(sum(a) / len(a), 3) if a else None
    # 估算累计净盈亏(USD):兑现 net_bps × 名义额,粗口径(实际盈亏看对账)
    pnl = sum(_f(r.get("realized_net_bps")) / 1e4 * _f(r.get("notional_usd")) for r in rows if r.get("outcome") == "OK")
    return {
        "total": {"trades": tot["trades"], "ok": tot["ok"], "naked": tot["naked"], "halt": tot["halt"],
                  "avg_capture": avg(tot["caps"]), "avg_realized_net": avg(tot["nets"]),
                  "avg_paper_net": avg(tot["papers"]),
                  "pos_caps": sum(1 for c in tot["caps"] if c > 0), "neg_caps": sum(1 for c in tot["caps"] if c <= 0),
                  "est_pnl_usd": round(pnl, 4)},
        "today": tod,
    }


def _recent(rows: list[dict], n: int = 20) -> list[dict]:
    out = []
    for r in rows[-n:][::-1]:
        try:
            bj = (datetime.fromtimestamp(int(r["ts_seen"]) / 1000, timezone.utc) + timedelta(hours=8)).strftime("%m-%d %H:%M:%S")
        except (ValueError, TypeError, KeyError):
            bj = "-"
        out.append({
            "time": bj, "outcome": r.get("outcome", ""),
            "paper_net": _f(r.get("paper_net_bps")), "realized_net": _f(r.get("realized_net_bps")),
            "capture": _f(r.get("capture_ratio")),
            "buy_price": _f(r.get("buy_eff_price")), "short_price": _f(r.get("short_avg_price")),
            "ms_to_buy": int(_f(r.get("ms_to_buy"))), "note": (r.get("note") or "")[:60],
        })
    return out


def _heartbeat_read() -> dict:
    """读 coordinator 心跳文件,判断 worker 是否在跑(最近心跳<15s=alive)。零网络成本。"""
    out = {"alive": False, "age_sec": None, "tick": None, "net": None,
           "mode": None, "trigger": None, "halted": None, "trades": None, "poll_sec": None}
    try:
        import json
        path = os.path.join(os.path.dirname("./data/exec_log.csv") or ".", "exec_heartbeat.json")
        with open(path, encoding="utf-8") as f:
            hb = json.load(f)
        age = (time.time() * 1000 - hb.get("ts", 0)) / 1000
        out.update(alive=(age < 15), age_sec=round(age, 1), tick=hb.get("tick"),
                   net=hb.get("net"), mode=hb.get("mode"), trigger=hb.get("trigger"),
                   halted=hb.get("halted"), trades=hb.get("trades"), poll_sec=hb.get("poll_sec"))
    except Exception:  # noqa: BLE001
        pass
    return out


def _spread_now() -> dict:
    """当前基差(KyberSwap报价 vs 币安,~150ms)。轻量,1.5s缓存,给前端快刷。"""
    now = time.time()
    if _SPREAD_CACHE["data"] and now - _SPREAD_CACHE["ts"] < _SPREAD_TTL:
        return _SPREAD_CACHE["data"]
    out = {"spread": None, "errors": []}
    try:
        from .binance_exec import BinanceExec, FUTURES_LIVE
        from .onchain_exec import OnchainExec
        from .spread_calc import compute_spread
        m, ch = _market_ctx()
        bn = BinanceExec(cfg.bn_api_key, cfg.bn_api_secret, FUTURES_LIVE)
        oc = OnchainExec("dry-run", cfg.exec_wallet_addr, "", cfg.kyber_client_id)
        q = oc.quote_buy(m, cfg.exec_notional_usd)
        bt = bn.book_ticker(m.binance_symbol)
        sp = compute_spread(
            market=m.key, binance_symbol=m.binance_symbol, ts=int(now * 1000),
            dex_eff_price=q.eff_price, dex_mid_price=q.mid_price, base_out=q.base_out,
            slippage_bps=q.slippage_bps, gas_usd=(q.gas_usd or 0.01),
            fut_bid=float(bt["bid"]), fut_ask=float(bt["ask"]), notional_usd=cfg.exec_notional_usd,
            taker_fee_bps=cfg.taker_fee_bps, recycle_bps=ch.recycle_bps,
            min_net_bps=cfg.exec_min_net_bps, exit_floor_bps=cfg.exit_floor_bps)
        out["spread"] = {"gross": round(sp.gross_bps, 2), "net": round(sp.net_bps, 2),
                         "trigger": cfg.exec_min_net_bps, "gap": round(cfg.exec_min_net_bps - sp.net_bps, 2),
                         "dex_price": round(q.eff_price, 1), "bn_bid": float(bt["bid"]),
                         "ts": int(now * 1000)}
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"spread: {type(e).__name__}")
    _SPREAD_CACHE["ts"] = now
    _SPREAD_CACHE["data"] = out
    return out


def _balances() -> dict:
    """链上余额 + 币安持仓(重,变化慢)。8s缓存。按当前 market 自适应,不写死OP/WBTC/BTCUSDT。"""
    now = time.time()
    if _BAL_CACHE["data"] and now - _BAL_CACHE["ts"] < _BAL_TTL:
        return _BAL_CACHE["data"]
    out = {"chain": None, "binance": None, "errors": []}
    m, ch = _market_ctx()
    W = cfg.exec_wallet_addr
    base_sym = cfg.exec_market.split(":")[-1] if ":" in cfg.exec_market else "BASE"
    try:
        from .chain_rpc import ChainRpc
        rpc = ChainRpc(cfg.exec_rpc, ch.chain_id, timeout=8)
        base_bal = rpc.erc20_balance(m.base_token, W) / (10 ** m.base_decimals) if m else 0.0
        out["chain"] = {
            "base": round(base_bal, 8), "base_sym": base_sym,
            "stable": round(rpc.erc20_balance(ch.stable, W) / (10 ** ch.stable_decimals), 2),
            "native": round(rpc.eth_balance(W) / 1e18, 6),
            # 兼容旧前端字段名
            "wbtc": round(base_bal, 8),
            "usdc": round(rpc.erc20_balance(ch.stable, W) / (10 ** ch.stable_decimals), 2),
            "eth": round(rpc.eth_balance(W) / 1e18, 6),
        }
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"chain: {type(e).__name__}")
    try:
        from .binance_exec import BinanceExec, FUTURES_LIVE
        sym = m.binance_symbol if m else "BTCUSDT"
        bn = BinanceExec(cfg.bn_api_key, cfg.bn_api_secret, FUTURES_LIVE)
        pos = [p for p in bn._request("GET", "/fapi/v2/positionRisk", {"symbol": sym})
               if abs(_f(p.get("positionAmt"))) > 0]
        out["binance"] = {
            "short": _f(pos[0]["positionAmt"]) if pos else 0.0,
            "entry": _f(pos[0]["entryPrice"]) if pos else 0.0,
            "upnl": _f(pos[0]["unRealizedProfit"]) if pos else 0.0,
            "sym": sym,
        }
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"binance: {type(e).__name__}")
    _BAL_CACHE["ts"] = now
    _BAL_CACHE["data"] = out
    return out


def _live_blocks() -> dict:
    """实时持仓对账 + 当前基差(合并三个数据源,供全量端点)。"""
    bal = _balances()
    sp = _spread_now()
    return {"chain": bal.get("chain"), "binance": bal.get("binance"),
            "spread": sp.get("spread"), "errors": bal.get("errors", []) + sp.get("errors", [])}


def live_light() -> dict:
    """轻量实时端点:仅基差 + worker心跳。给前端高频刷(1.5s),不查链上余额。"""
    return {"spread": _spread_now().get("spread"), "worker": _heartbeat_read()}



def monitor_snapshot() -> dict:
    """面板总数据。配置区不含任何 secret。"""
    rows = _read_exec_rows()
    # 两腿匹配判断
    live = _live_blocks()
    match = None
    if live.get("chain") and live.get("binance") is not None:
        base = live["chain"].get("base", live["chain"].get("wbtc", 0)); short = abs(live["binance"]["short"])
        # 容差按量级:CAKE等整数级币留1单位(避开卖回零头误报),BTC等小数级留0.0005
        tol = 1.0 if max(base, short) > 10 else 0.0005
        if base > tol or short > tol:
            match = abs(base - short) <= tol
    bj_now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "now_bj": bj_now,
        "config": {"mode": cfg.exec_mode, "market": cfg.exec_market,
                   "notional_usd": cfg.exec_notional_usd, "trigger_bps": cfg.exec_min_net_bps,
                   "max_trades": cfg.exec_max_trades, "max_daily_usd": cfg.exec_max_daily_usd},
        "summary": _summary(rows),
        "recent": _recent(rows),
        "live": live,
        "worker": _heartbeat_read(),
        "hedge_match": match,
    }
