"""CrossArb P0 入口:启动多市场并行采集线程 + FastAPI 看板。

run:  python -m app.main
看板:http://<host>:8100/        API:/api/stats  /api/health
默认只听 127.0.0.1(nginx 在前);本机直连调试设 CROSSARB_HTTP_HOST=0.0.0.0。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from .collector import Collector
from .config import cfg
from .markets import load_markets
from .options_fill_state import OptionsState
from .options_probe import OptionsParityProbe
from .report import build_report
from .state import State

state = State(csv_path=cfg.csv_path, redis_url=cfg.redis_url, min_net_bps=cfg.min_net_bps)
collector = Collector(state)

options_state = OptionsState(csv_path=cfg.options_csv, redis_url=cfg.redis_url,
                             min_net_bps=cfg.options_min_net_bps)
options_probe = OptionsParityProbe(options_state)

_STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    collector.start()
    options_probe.start()
    try:
        yield
    finally:
        collector.stop()
        options_probe.stop()


app = FastAPI(title="CrossArb P0 — 只读经济性验证(多市场)", lifespan=lifespan)


@app.get("/api/stats")
def api_stats():
    return JSONResponse(state.snapshot())


@app.get("/api/health")
def api_health():
    return {
        "ok": True,
        "chain": "base",
        "min_net_bps": cfg.min_net_bps,
        "poll_sec": cfg.poll_sec,
        "notional_usd": cfg.notional_usd,
        "markets": [
            {"key": m.key, "binance": m.binance_symbol, "fee_tier": m.fee_tier}
            for m in load_markets()
        ],
    }


@app.get("/api/report")
def api_report(threshold: Optional[float] = None, start_ms: Optional[int] = None, end_ms: Optional[int] = None):  # Optional 而非 float|None,兼容 Python 3.9(AL2023)
    thr = cfg.min_net_bps if threshold is None else threshold
    return JSONResponse(build_report(cfg.csv_path, thr, depth=state.depth_snapshot(),
                                     start_ms=start_ms, end_ms=end_ms))


@app.get("/api/p1")
def api_p1():
    """P1 真金执行监控数据(只读旁路:读 exec_log.csv + 实时对账,不碰 coordinator)。"""
    from .p1_monitor import monitor_snapshot
    return JSONResponse(monitor_snapshot())


@app.get("/api/p1/live")
def api_p1_live():
    """轻量实时端点:仅当前基差 + worker心跳。前端高频刷(不查链上余额,~150ms)。"""
    from .p1_monitor import live_light
    return JSONResponse(live_light())


@app.get("/", response_class=HTMLResponse)
def index():
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/report", response_class=HTMLResponse)
def report_page():
    return (_STATIC / "report.html").read_text(encoding="utf-8")


@app.get("/p1", response_class=HTMLResponse)
def p1_page():
    return (_STATIC / "p1.html").read_text(encoding="utf-8")


@app.get("/api/dexarb")
def api_dexarb():
    """DEX-DEX 影子测量数据(只读,供 dd.hustle2026.xyz)。"""
    from .dexarb_monitor import shadow_snapshot
    return JSONResponse(shadow_snapshot())


@app.get("/api/options")
def api_options():
    """币安期权买卖权平价只读探针数据(只能 KILL/证伪;KEEP 需真金 canary)。"""
    return JSONResponse(options_state.snapshot())


@app.get("/options", response_class=HTMLResponse)
def options_page():
    return (_STATIC / "options.html").read_text(encoding="utf-8")


@app.get("/dexarb", response_class=HTMLResponse)
def dexarb_page():
    return (_STATIC / "dexarb.html").read_text(encoding="utf-8")


@app.get("/api/cexdex")
def api_cexdex():
    """CEX-DEX 价差存活测量数据(只读)。"""
    from .cexdex_monitor import cexdex_snapshot
    return JSONResponse(cexdex_snapshot())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=cfg.http_host, port=cfg.http_port)
