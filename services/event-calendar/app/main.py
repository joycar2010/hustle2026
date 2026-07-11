"""event-calendar v1:事件驱动日历(蓝图机会外挂层第一件)。

监控两类事件,数据源=universe-sync 已落地的逐所宇宙键(不新增交易所调用):
① 新永续上市:universe 出现 first_seen 没见过的合约 → 事件+飞书告警。
   新永续首日费率极端是双合约引擎的高频客户;advisor 的 funding 扫描会自然
   接住机会,本服务的职责是"第一时间出声+记录上市时刻"(age_days 标签的源头)。
② 疑似下架/暂停:近 7 天见过的合约从 universe 消失 → 告警;
   若消失的币恰好是 dualperp/basis 在场持仓 → fatal(持仓币下架=清算风险,须人工)。

键契约:
  dcm:event:first_seen   HSET {venue}:{native_sym} -> first_seen_ts(持久,上市时刻账本)
  dcm:event:new_listings LPUSH JSON(近事件流,LTRIM 200)
  dcm:hb:event-calendar  心跳

冷启动纪律:first_seen 为空(首轮)只登记不告警——否则全宇宙 4000+ 合约都是"新上市"。
消失去抖:连续 2 轮不见才判消失(universe-sync 单轮抖动/收缩保护窗口不误报)。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat
from dcm_common.notify import Notifier, feishu_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("event-calendar")

SERVICE = "event-calendar"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_EVCAL_INTERVAL_SEC", "300"))
VENUES = ["binance", "okx", "bybit", "gate", "bitget", "hyperliquid"]
FIRST_SEEN_KEY = "dcm:event:first_seen"
EVENTS_KEY = "dcm:event:new_listings"
GONE_STRIKES = 2          # 消失去抖轮数
RECENT_WINDOW_SEC = 7 * 86400  # "近期见过"窗口:超窗的消失不再追(历史退市噪音)

_gone_hits: dict[str, int] = {}


def _norm(venue: str, native: str) -> str:
    """native → 统一符号(BTCUSDT)。宽松版,仅用于与持仓币对表;告警仍带 native。"""
    s = native.upper().replace("-USDT-SWAP", "USDT").replace("_USDT", "USDT").replace("-USDT", "USDT")
    s = s.replace("-", "").replace("_", "")
    if venue == "hyperliquid" and not s.endswith("USDT"):
        s += "USDT"
    return s


async def _held_symbols(r: aioredis.Redis) -> set[str]:
    """dualperp+basis 在场持仓的统一符号(下架撞持仓要升 fatal)。"""
    held: set[str] = set()
    for key in ("dcm:engine:dualperp:positions", "dcm:engine:basis:positions"):
        try:
            d = json.loads(await r.get(key) or "{}")
            for p in d.get("positions") or []:
                if p.get("symbol"):
                    held.add(p["symbol"])
        except Exception:
            continue
    return held


# ── ③公告前瞻(best-effort;失败不影响下方可靠的 universe 差分兜底)──
# 新永续常提前数小时公告,universe 差分是上线后才见——公告给提前量喂主力引擎。
# 币安公告 CMS 有 WAF/限频:非 JSON/异常一律跳过本轮,绝不崩;已见文章 id 去重持久化。
ANN_CATALOGS = {48: "上新", 161: "下架"}   # catalogId→标签
ANN_SEEN_KEY = "dcm:event:seen_articles"
ANN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_ANN_KW_PERP = ("perpetual", "u本位", "永续", "usdⓈ-m", "usdⓈ-m")
_ANN_KW_DELIST = ("delist", "下架", "will delist", "removal")


async def announcement_poll(r: aioredis.Redis, cli: httpx.AsyncClient, notify: Notifier) -> dict:
    seen = 0
    fired = 0
    # 冷启动:seen set 为空首轮只登记历史公告不告警(否则全历史当新刷屏,同 universe bootstrap)
    bootstrap = (await r.scard(ANN_SEEN_KEY)) == 0
    for cid, label in ANN_CATALOGS.items():
        try:
            resp = await cli.get(
                "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                params={"type": 1, "catalogId": cid, "pageNo": 1, "pageSize": 10},
                headers={"User-Agent": ANN_UA, "clienttype": "web", "lang": "en"}, timeout=15)
            if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("application/json"):
                continue
            cats = resp.json().get("data", {}).get("catalogs", [])
        except Exception:
            continue  # WAF/限频/非JSON:跳过本轮,universe 差分兜底
        if not cats:
            continue
        for a in (cats[0].get("articles") or []):
            aid = str(a.get("id") or a.get("code") or "")
            title = (a.get("title") or "").strip()
            if not aid or not title:
                continue
            # 已见去重(持久 set)
            if await r.sismember(ANN_SEEN_KEY, aid):
                continue
            await r.sadd(ANN_SEEN_KEY, aid)
            seen += 1
            low = title.lower()
            is_perp = any(k in low for k in _ANN_KW_PERP)
            is_delist = any(k in low for k in _ANN_KW_DELIST)
            ev = {"type": "announcement", "catalog": label, "id": aid, "title": title,
                  "perp": is_perp, "delist": is_delist, "ts": int(time.time())}
            await r.lpush(EVENTS_KEY, json.dumps(ev, ensure_ascii=False))
            # 只对"新永续"与"下架"两类高价值公告出声(避免普通公告刷屏)
            if is_perp and label == "上新" and not bootstrap:
                fired += 1
                await asyncio.to_thread(
                    notify.fire, f"ann-perp:{aid}", "新永续公告(提前量)",
                    f"币安公告:{title[:80]}——永续上线预告,先于 universe 差分,关注费率窗口", level="warn")
            elif (is_delist or label == "下架") and not bootstrap:
                fired += 1
                await asyncio.to_thread(
                    notify.fire, f"ann-delist:{aid}", "下架公告",
                    f"币安公告:{title[:80]}——若命中在场持仓立即人工核", level="warn")
    # seen set 防无限膨胀:保留最近(SPOP 到上限)
    try:
        n = await r.scard(ANN_SEEN_KEY)
        if n > 2000:
            await r.spop(ANN_SEEN_KEY, n - 2000)
    except Exception:
        pass
    return {"new_articles": seen, "fired": fired}


async def calendar_round(r: aioredis.Redis, notify: Notifier) -> dict:
    now = int(time.time())
    first_seen = await r.hgetall(FIRST_SEEN_KEY)
    bootstrap = len(first_seen) == 0
    new_events, gone_events = [], []
    held = await _held_symbols(r)

    present: set[str] = set()
    for v in VENUES:
        for key in (f"dcm:feed:universe:{v}:perp", f"dcm:feed:universe:{v}"):
            try:
                raw = await r.get(key)
            except Exception:
                raw = None
            if raw:
                break
        if not raw:
            continue
        try:
            syms = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(syms, list) or len(syms) < 5:
            continue  # 宇宙异常缩水本轮不判(universe-sync 有收缩保护,这里同样保守)
        for native in syms:
            field = f"{v}:{native}"
            present.add(field)
            if field not in first_seen:
                await r.hset(FIRST_SEEN_KEY, field, str(now))
                if not bootstrap:
                    uni = _norm(v, native)
                    ev = {"type": "new_perp", "venue": v, "native": native,
                          "symbol": uni, "ts": now}
                    new_events.append(ev)
                    await r.lpush(EVENTS_KEY, json.dumps(ev, ensure_ascii=False))
                    await asyncio.to_thread(
                        notify.fire,
                        f"newperp:{v}:{uni}", f"新永续上市 {v} {native}",
                        f"统一符号 {uni};首日费率常极端,双合约引擎的高频客户——"
                        f"advisor 下轮费率扫描将自动纳入,关注费差榜", level="warn")

    # 消失检测:近期见过 + 本轮不在 + 连续 GONE_STRIKES 轮
    for field, ts in first_seen.items():
        if field in present:
            _gone_hits.pop(field, None)
            continue
        if now - int(ts) > RECENT_WINDOW_SEC and field not in _gone_hits:
            continue  # 超窗历史退市,不追溯(但已在计数中的继续走完)
        _gone_hits[field] = _gone_hits.get(field, 0) + 1
        if _gone_hits[field] == GONE_STRIKES:
            v, native = field.split(":", 1)
            uni = _norm(v, native)
            ev = {"type": "delisted", "venue": v, "native": native, "symbol": uni, "ts": now}
            gone_events.append(ev)
            await r.lpush(EVENTS_KEY, json.dumps(ev, ensure_ascii=False))
            level = "fatal" if uni in held else "warn"
            extra = "⚠️该币当前在场持仓,下架=清算/交割风险,立即人工处置!" if uni in held else \
                    "已从宇宙消失(下架/暂停/流动性跌出地板)"
            await asyncio.to_thread(notify.fire, f"delist:{v}:{uni}",
                                    f"合约消失 {v} {native}", extra, level=level)
            await r.hdel(FIRST_SEEN_KEY, field)
            _gone_hits.pop(field, None)

    await r.ltrim(EVENTS_KEY, 0, 199)
    return {"tracked": len(first_seen) + len(new_events), "new": len(new_events),
            "gone": len(gone_events), "bootstrap": bootstrap, "held": len(held)}


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    notify = Notifier(REDIS_URL, SERVICE, feishu=feishu_from_env())
    hb = Heartbeat(REDIS_URL, SERVICE, interval_sec=60, ttl_sec=1200)
    asyncio.create_task(hb.run_forever())
    _ann_cli = httpx.AsyncClient(timeout=20)
    log.info(f"event-calendar up interval={INTERVAL}s venues={VENUES} (含③公告前瞻)")
    while True:
        try:
            stats = await calendar_round(r, notify)
            try:
                ann = await announcement_poll(r, _ann_cli, notify)
                stats["ann"] = ann
            except Exception:
                log.warning("announcement poll failed (universe diff 兜底继续)", exc_info=True)
            hb.extra = stats
            log.info(f"CALENDAR_OK {stats}")
        except Exception:
            log.exception("calendar round crashed (continuing)")
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
