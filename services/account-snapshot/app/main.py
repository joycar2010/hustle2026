"""account-snapshot(B 机):五所真实账户只读快照发布器。

API key 白名单只绑 B 机 → 所有交易所私有调用只从 B 发起,key 只存 B 一处;
风控面 risk-ledger(C 机)读 Redis 快照做对账,永不持 key——与 coin-bridge 同一隔离哲学。

键契约:dcm:account:{venue} = {ts, ok, equity_usdt, positions, err}(EX 180)
        dcm:hb:account-snapshot 逐所 ok/equity 计数
只读:本服务无任何下单能力。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

from dcm_common.exchanges import fetch_account

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("account-snapshot")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_ACCT_INTERVAL_SEC", "60"))

VENUE_CFG = {
    "binance": {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")},
    "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
    "okx": {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
            "passphrase": os.environ.get("OKX_PASSPHRASE", "")},
    "gate": {"key": os.environ.get("GATE_KEY", ""), "secret": os.environ.get("GATE_SECRET", "")},
    "bitget": {"key": os.environ.get("BITGET_KEY", ""), "secret": os.environ.get("BITGET_SECRET", ""),
               "passphrase": os.environ.get("BITGET_PASSPHRASE", "")},
    # HL 第六腿只读:info 端点免签名,地址即凭证(交易腿等钱包私钥到位另期)
    "hyperliquid": {"key": os.environ.get("HL_WALLET_ADDRESS", ""), "secret": "-",
                    "address": os.environ.get("HL_WALLET_ADDRESS", "")},
}


CREDS_DIR = os.path.expanduser("~/dexcexmix/.creds")


def _venue_proxy(venue: str) -> str:
    """读该 venue 的 IP 代理出口（cred-agent 写 .creds/{venue}.env 的 PROXY_URL）。
    无文件/无 PROXY_URL = 直连（当前所有账户零行为变化）。"""
    path = os.path.join(CREDS_DIR, f"{venue}.env")
    if not os.path.exists(path):
        return ""
    try:
        for line in open(path):
            if line.startswith("PROXY_URL="):
                return line.split("=", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    active = {v: c for v, c in VENUE_CFG.items() if c.get("key") and c.get("secret")}
    # 逐所构造客户端：有 PROXY_URL 走代理出口,否则共享直连客户端（IP 代理消费落地）
    shared = httpx.AsyncClient(timeout=15)
    proxied: dict[str, httpx.AsyncClient] = {}
    proxy_sig: dict[str, str] = {}

    def client_for(venue: str) -> httpx.AsyncClient:
        px = _venue_proxy(venue)
        if not px:
            if venue in proxied:  # 代理被移除→回落直连,关旧客户端
                old = proxied.pop(venue); proxy_sig.pop(venue, None)
                asyncio.get_event_loop().create_task(old.aclose())
            return shared
        if proxy_sig.get(venue) != px:  # 代理变更→重建
            if venue in proxied:
                asyncio.get_event_loop().create_task(proxied[venue].aclose())
            proxied[venue] = httpx.AsyncClient(timeout=15, proxies=px)
            proxy_sig[venue] = px
            log.info("venue %s via proxy %s", venue, px.split("@")[-1] if "@" in px else px)
        return proxied[venue]

    log.info("account-snapshot up interval=%ss venues=%s", INTERVAL, list(active))
    try:
        while True:
            try:
                snaps = await asyncio.gather(*(fetch_account(client_for(v), v, c) for v, c in active.items()))
                hb = {"service": "account-snapshot", "ts": int(time.time()), "pid": os.getpid()}
                for s in snaps:
                    await r.set(f"dcm:account:{s.venue}", json.dumps({
                        "ts": int(time.time()), "ok": s.ok, "equity_usdt": round(s.equity_usdt, 2),
                        "positions": {k: round(v, 10) for k, v in s.positions.items()},
                        "pos_detail": s.pos_detail,
                        "err": s.err}, ensure_ascii=False), ex=180)
                    hb[s.venue] = f"{round(s.equity_usdt, 2)}U/{len(s.positions)}pos" if s.ok else f"ERR:{s.err[:60]}"
                await r.set("dcm:hb:account-snapshot", json.dumps(hb, ensure_ascii=False), ex=max(INTERVAL * 3, 300))
                log.info("ACCT_OK %s", {s.venue: (s.ok, round(s.equity_usdt, 2), len(s.positions)) for s in snaps})
            except Exception:
                log.exception("snapshot round crashed (continuing)")
            await asyncio.sleep(INTERVAL)
    finally:
        await shared.aclose()
        for c in proxied.values():
            await c.aclose()


if __name__ == "__main__":
    asyncio.run(main())
