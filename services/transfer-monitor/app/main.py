"""transfer-monitor v1:充提状态监控(蓝图风控面补盲区)。

风控盲区:持仓币一旦被暂停提现,常是下架/脱锚前兆——risk-ledger 现在完全看不见。
本服务纯读币安 capital/config(一次调用返全部币逐网络充提开关),逐币归并"任一网络可充/可提",
发布状态快照 + 检测 开→关 转变;**持仓币被暂停提现即 fatal**(下架/交割/脱锚风险)。

跑在 B 机(key 所在)。纯读,绝无划转/提现动作。币安为主(coin 持仓与现货腿都在币安)。

键契约:
  dcm:coin:transfer_status  HSET {ASSET} -> {dep, wd, ts}(dep/wd=任一网络可充/可提)
  dcm:coin:transfer_events  LPUSH JSON(充提开关转变流,LTRIM 200)
  dcm:risk:withdrawal:{venue}  提现健康(五所:binance/bybit/okx/gate/bitget;risk-ledger 消费)
  dcm:hb:transfer-monitor   心跳

持仓集 = dualperp/basis/coin 三引擎快照并集(base 资产);持仓币提现被停 → fatal 告警。
去抖:转变事件按 (asset,field,方向) 冷却;冷启动只登记不告警。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat
from dcm_common.notify import Notifier, feishu_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("transfer-monitor")

SERVICE = "transfer-monitor"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_TRANSFER_INTERVAL_SEC", "300"))
EVENT_COOLDOWN = int(os.environ.get("DCM_TRANSFER_EVENT_COOLDOWN_SEC", "1800"))
KEY_STATUS = "dcm:coin:transfer_status"
KEY_EVENTS = "dcm:coin:transfer_events"

BINANCE = {"key": os.environ.get("BINANCE_KEY", ""), "secret": os.environ.get("BINANCE_SECRET", "")}

_prev: dict[str, tuple] = {}          # ASSET -> (dep, wd)
_evt_cooldown: dict[str, float] = {}  # "{ASSET}:{field}:{dir}" -> ts


async def _binance_capital(cli: httpx.AsyncClient) -> dict[str, dict] | None:
    """全币逐网络充提开关。归并:任一网络可充→dep=True;任一网络可提→wd=True。失败 None。"""
    q = urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
    sig = hmac.new(BINANCE["secret"].encode(), q.encode(), hashlib.sha256).hexdigest()
    try:
        r = (await cli.get(f"https://api.binance.com/sapi/v1/capital/config/getall?{q}&signature={sig}",
                           headers={"X-MBX-APIKEY": BINANCE["key"]})).json()
        if not isinstance(r, list):
            return None
        out = {}
        for x in r:
            nets = x.get("networkList") or []
            out[x["coin"].upper()] = {
                "dep": any(n.get("depositEnable") for n in nets),
                "wd": any(n.get("withdrawEnable") for n in nets),
            }
        return out
    except Exception:
        return None


# ───────── WithdrawalSentinel(V5 §6.4):五所提现健康进料口 ─────────
# 归一记录 (cls, t0, t1):cls∈pending|done|fail|cancel;t0=发起 epoch;t1=完成 epoch(所无完成时间字段则 None)。
# 无 key / 拉取失败 → 不发布(键过期,policy 对无键 venue 按 NORMAL——如实缺席,不猜不误伤)。
# 用户主动 cancel 不计入 recent_failures(连败→NO_NEW 只该由平台拒绝/失败触发)。
# hyperliquid 提现=链上桥出金,无 pending 语义,不设进料口。
# ⚠️读提现历史各所都只需读权限,不需提现权限。

CREDS = {
    "bybit": {"key": os.environ.get("BYBIT_KEY", ""), "secret": os.environ.get("BYBIT_SECRET", "")},
    "okx": {"key": os.environ.get("OKX_KEY", ""), "secret": os.environ.get("OKX_SECRET", ""),
            "passphrase": os.environ.get("OKX_PASSPHRASE", "")},
    "gate": {"key": os.environ.get("GATE_KEY", ""), "secret": os.environ.get("GATE_SECRET", "")},
    "bitget": {"key": os.environ.get("BITGET_KEY", ""), "secret": os.environ.get("BITGET_SECRET", ""),
               "passphrase": os.environ.get("BITGET_PASSPHRASE", "")},
}


async def _wd_binance(cli) -> list | None:
    """status: 0邮件已发/2待审/4处理中=pending;6=done;3拒绝/5失败=fail;1=用户撤销。
    applyTime/completeTime 为 UTC 字符串(服务器 TZ=UTC,mktime 解析正确)。"""
    q = urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
    sig = hmac.new(BINANCE["secret"].encode(), q.encode(), hashlib.sha256).hexdigest()
    r = (await cli.get(f"https://api.binance.com/sapi/v1/capital/withdraw/history?{q}&signature={sig}",
                       headers={"X-MBX-APIKEY": BINANCE["key"]})).json()
    if not isinstance(r, list):
        return None

    def _ts(s):
        try:
            return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S"))
        except Exception:  # noqa: BLE001
            return 0

    cls_map = {0: "pending", 2: "pending", 4: "pending", 6: "done", 3: "fail", 5: "fail", 1: "cancel"}
    return [(cls_map.get(int(w.get("status", -1)), "pending"), _ts(w.get("applyTime")),
             _ts(w.get("completeTime")) or None) for w in r]


async def _wd_bybit(cli) -> list | None:
    cfg, q = CREDS["bybit"], "limit=50"
    ts = str(int(time.time() * 1000))
    sign = hmac.new(cfg["secret"].encode(), (ts + cfg["key"] + "5000" + q).encode(), hashlib.sha256).hexdigest()
    r = (await cli.get(f"https://api.bybit.com/v5/asset/withdraw/query-record?{q}",
                       headers={"X-BAPI-API-KEY": cfg["key"], "X-BAPI-TIMESTAMP": ts,
                                "X-BAPI-RECV-WINDOW": "5000", "X-BAPI-SIGN": sign})).json()
    if r.get("retCode") != 0:
        return None
    cls_map = {"success": "done", "Reject": "fail", "Fail": "fail", "CancelByUser": "cancel"}
    out = []
    for w in r.get("result", {}).get("rows", []) or []:
        cls = cls_map.get(w.get("status"), "pending")   # SecurityCheck/Pending/BlockchainConfirmed 等=pending
        t0 = float(w.get("createTime") or 0) / 1000
        t1 = float(w.get("updateTime") or 0) / 1000 if cls == "done" else None
        out.append((cls, t0, t1))
    return out


async def _wd_okx(cli) -> list | None:
    """state: -1=fail / -2,-3=cancel / 2=done / 其余(0,1,4..17 审核中/广播中)=pending。无完成时间字段。"""
    cfg, path = CREDS["okx"], "/api/v5/asset/withdrawal-history"
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
    sign = base64.b64encode(hmac.new(cfg["secret"].encode(), (ts + "GET" + path).encode(),
                                     hashlib.sha256).digest()).decode()
    r = (await cli.get(f"https://www.okx.com{path}",
                       headers={"OK-ACCESS-KEY": cfg["key"], "OK-ACCESS-SIGN": sign,
                                "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": cfg["passphrase"]})).json()
    if r.get("code") != "0":
        return None
    out = []
    for w in r.get("data", []) or []:
        st = str(w.get("state"))
        cls = "fail" if st == "-1" else "cancel" if st in ("-2", "-3") else "done" if st == "2" else "pending"
        out.append((cls, float(w.get("ts") or 0) / 1000, None))
    return out


async def _wd_gate(cli) -> list | None:
    """status: DONE=done / FAIL,INVALID=fail / CANCEL=cancel / 其余(REQUEST/MANUAL/VERIFY/PEND…)=pending。"""
    cfg, path = CREDS["gate"], "/wallet/withdrawals"
    ts = str(int(time.time()))
    body_hash = hashlib.sha512(b"").hexdigest()
    pre = f"GET\n/api/v4{path}\n\n{body_hash}\n{ts}"
    sign = hmac.new(cfg["secret"].encode(), pre.encode(), hashlib.sha512).hexdigest()
    r = (await cli.get(f"https://api.gateio.ws/api/v4{path}",
                       headers={"KEY": cfg["key"], "Timestamp": ts, "SIGN": sign})).json()
    if not isinstance(r, list):
        return None
    cls_map = {"DONE": "done", "FAIL": "fail", "INVALID": "fail", "CANCEL": "cancel"}
    return [(cls_map.get(w.get("status"), "pending"), float(w.get("timestamp") or 0), None) for w in r]


async def _wd_bitget(cli) -> list | None:
    """status: success=done / fail=fail / pending=pending;窗口参数必填,取 30d。"""
    cfg = CREDS["bitget"]
    now_ms = int(time.time() * 1000)
    path = "/api/v2/spot/wallet/withdrawal-records"
    q = f"startTime={now_ms - 30 * 86400000}&endTime={now_ms}&limit=100"
    ts = str(now_ms)
    sign = base64.b64encode(hmac.new(cfg["secret"].encode(), (ts + "GET" + path + "?" + q).encode(),
                                     hashlib.sha256).digest()).decode()
    r = (await cli.get(f"https://api.bitget.com{path}?{q}",
                       headers={"ACCESS-KEY": cfg["key"], "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
                                "ACCESS-PASSPHRASE": cfg["passphrase"], "locale": "en-US"})).json()
    if r.get("code") != "00000":
        return None
    cls_map = {"success": "done", "fail": "fail"}
    out = []
    for w in r.get("data", []) or []:
        cls = cls_map.get(w.get("status"), "pending")
        t0 = float(w.get("cTime") or 0) / 1000
        t1 = float(w.get("uTime") or 0) / 1000 if cls == "done" else None
        out.append((cls, t0, t1))
    return out


_WD_COLLECTORS = {"binance": _wd_binance, "bybit": _wd_bybit, "okx": _wd_okx,
                  "gate": _wd_gate, "bitget": _wd_bitget}


def _wd_summary(venue: str, recs: list, now: float) -> dict:
    """归一记录→健康摘要:pending 龄/时长 p50-p95/平台失败数/最后成功。
    提现罕见(交易 key 提现关,仅 Treasury 手动),样本少时 p50/p95=None,靠 pending 龄+SLA 兜底。"""
    pending_ages, durations, fails, last_success = [], [], 0, 0
    for cls, t0, t1 in recs:
        if cls == "pending" and t0:
            pending_ages.append(now - t0)
        elif cls == "done":
            last_success = max(last_success, t0)
            if t1 and t0 and t1 >= t0:
                durations.append(t1 - t0)
        elif cls == "fail":
            fails += 1
    durations.sort()

    def _pct(arr, p):
        return round(arr[min(len(arr) - 1, int(len(arr) * p))], 1) if arr else None

    return {"ts": int(now), "venue": venue,
            "pending_count": len(pending_ages),
            "oldest_pending_age_sec": int(max(pending_ages)) if pending_ages else 0,
            "p50_sec": _pct(durations, 0.5), "p95_sec": _pct(durations, 0.95),
            "sample_n": len(durations), "recent_failures": fails,
            "last_success_at": int(last_success)}


async def _held_assets(r: aioredis.Redis) -> set[str]:
    """dualperp/basis/coin 三引擎在场持仓的 base 资产。"""
    held: set[str] = set()
    for key in ("dcm:engine:dualperp:positions", "dcm:engine:basis:positions", "dcm:engine:coin:positions"):
        try:
            d = json.loads(await r.get(key) or "{}")
            for p in d.get("positions") or []:
                sym = p.get("symbol") or ""
                if sym.endswith("USDT"):
                    held.add(sym[:-4].upper())
        except Exception:
            continue
    return held


async def monitor_round(r: aioredis.Redis, cli: httpx.AsyncClient, notify: Notifier) -> dict:
    now = int(time.time())
    caps = await _binance_capital(cli)
    if caps is None:
        return {"status": "capital_query_failed"}
    held = await _held_assets(r)
    events = held_alerts = 0
    pipe = r.pipeline()
    for asset, st in caps.items():
        pipe.hset(KEY_STATUS, asset, json.dumps({"dep": st["dep"], "wd": st["wd"], "ts": now}))
    await pipe.execute()
    await r.expire(KEY_STATUS, INTERVAL * 4)

    for asset, st in caps.items():
        prev = _prev.get(asset)
        _prev[asset] = (st["dep"], st["wd"])
        if prev is None:
            continue
        for field, idx, label in (("dep", 0, "充值"), ("wd", 1, "提现")):
            was, now_v = prev[idx], st[field]
            if was == now_v:
                continue
            direction = "off" if (was and not now_v) else "on"
            cdk = f"{asset}:{field}:{direction}"
            if now - _evt_cooldown.get(cdk, 0) < EVENT_COOLDOWN:
                continue
            _evt_cooldown[cdk] = now
            ev = {"asset": asset, "field": field, "direction": direction, "ts": now}
            await r.lpush(KEY_EVENTS, json.dumps(ev, ensure_ascii=False))
            events += 1
            # 持仓币提现被停 = 下架/交割/脱锚前兆 → fatal;其余转变 = warn
            if asset in held and field == "wd" and direction == "off":
                held_alerts += 1
                await asyncio.to_thread(
                    notify.fire, f"held-wd-off:{asset}", f"⚠️持仓币提现暂停 {asset}",
                    f"{asset}(在场持仓)币安提现已关闭——下架/交割/脱锚前兆,立即人工核持仓去留", level="fatal")
            elif direction == "off":
                await asyncio.to_thread(
                    notify.fire, f"{field}-off:{asset}", f"币安{label}暂停 {asset}",
                    f"{asset} 币安{label}关闭(非持仓)——风险信号,观察", level="warn")
    await r.ltrim(KEY_EVENTS, 0, 199)
    # WithdrawalSentinel:逐所发布提现健康供 risk-ledger 消费(提现延迟→WATCH/REDUCE 触发)。
    # 逐所隔离:一所拉取失败只影响该所(不发布→键过期→NORMAL),绝不拖垮整轮。
    wd_pending = {}
    for venue, collector in _WD_COLLECTORS.items():
        cfg = BINANCE if venue == "binance" else CREDS[venue]
        if not cfg.get("key"):
            continue
        try:
            recs = await collector(cli)
        except Exception:  # noqa: BLE001
            recs = None
        if recs is None:
            log.warning("withdrawal history fetch failed venue=%s (skip publish)", venue)
            continue
        wh = _wd_summary(venue, recs, time.time())
        await r.set(f"dcm:risk:withdrawal:{venue}", json.dumps(wh, ensure_ascii=False),
                    ex=max(INTERVAL * 4, 1200))
        if wh["pending_count"]:
            wd_pending[venue] = wh["pending_count"]
    return {"coins": len(caps), "held": len(held), "events": events, "held_alerts": held_alerts,
            "wd_pending": wd_pending}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    notify = Notifier(REDIS_URL, SERVICE, feishu=feishu_from_env())
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=60, ttl_sec=max(INTERVAL * 3, 900))
    asyncio.create_task(hb.run_forever())
    log.info(f"transfer-monitor up interval={INTERVAL}s")
    async with httpx.AsyncClient(timeout=20) as cli:
        while True:
            try:
                stats = await monitor_round(r, cli, notify)
                hb.extra = stats
                log.info(f"TRANSFER_OK {stats}")
            except Exception:
                log.exception("transfer-monitor round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
