"""时钟偏差监控 —— 保护点差新鲜度护栏。

点差三护栏(rust stale 10s / 本侧 _spread_fresh / 借币二次确认)都用 `now - ts` 判新鲜,
依赖交易主机(57)、点差源(95)、币安三方时钟一致。NTP 漂移会让护栏误判(放行陈旧 / 误杀新鲜)。
本模块周期性测两类偏差并飞书告警:
  1) 交易主机 ↔ 币安服务器时间(本地下单/校验口径)
  2) 点差 feed 摄入龄(95 写的 ts vs 币安时间)→ 反映 95 时钟 + 摄入健康
多 worker 用 redis NX 锁确保每周期仅一个执行,避免重复告警。
"""
from __future__ import annotations

import json
import logging
import time

import httpx

logger = logging.getLogger(__name__)

SKEW_ALERT_MS = 2000        # 本机↔币安 偏差告警阈值
FEED_AGE_ALERT_MS = 5000    # 点差 feed 摄入龄告警阈值
LOCK_KEY = "clock_skew_check_lock"
SERVER_TIME_URL = "https://fapi.binance.com/fapi/v1/time"


async def _alert(notifier, title: str, body: str) -> None:
    try:
        await notifier.send(title, body)
    except Exception:
        pass


async def run_clock_check(notifier, redis) -> None:
    # redis NX 锁:多 worker 每周期只一个真正执行(去重告警);锁不可用则照常执行(单实例)
    try:
        if redis is not None:
            got = await redis.set(LOCK_KEY, "1", nx=True, ex=290)
            if not got:
                return
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(SERVER_TIME_URL)
            server = int(r.json()["serverTime"])
    except Exception as e:
        logger.warning(f"Clock check: 取币安服务器时间失败: {e}")
        return

    # 1) 交易主机 ↔ 币安
    local = int(time.time() * 1000)
    skew = local - server
    if abs(skew) > SKEW_ALERT_MS:
        logger.warning(f"Clock skew vs Binance: {skew}ms (>{SKEW_ALERT_MS}ms) — 检查 NTP,影响点差新鲜度护栏")
        await _alert(notifier, "时钟偏差告警",
                     f"交易主机与币安时间差 {skew}ms(阈值 {SKEW_ALERT_MS}ms)\n"
                     f"会令点差新鲜度护栏失真,请检查 NTP(chronyd)。")
    else:
        logger.info(f"Clock skew vs Binance: {skew}ms (ok)")

    # 2) 点差 feed 摄入龄(95 时钟 + 摄入健康)
    try:
        raw = await redis.hget("spreads", "BTCUSDT") if redis is not None else None
        if raw:
            ts = int(json.loads(raw)["ts"])
            feed_age = server - ts  # 正常≈摄入延迟(几十ms);异常→95时钟偏/feed滞后
            if abs(feed_age) > FEED_AGE_ALERT_MS:
                logger.warning(f"Spread feed age (BTC) vs Binance: {feed_age}ms (>{FEED_AGE_ALERT_MS}ms)")
                await _alert(notifier, "点差源时钟/延迟告警",
                             f"点差源(10.0.1.95)BTC 摄入龄 {feed_age}ms(阈值 {FEED_AGE_ALERT_MS}ms)\n"
                             f"可能 95 时钟偏差或 feed 滞后,检查 95 的 NTP 与 cex-engine。")
    except Exception as fe:
        logger.debug(f"feed age check failed: {fe}")
