"""币安 API 文档变动检测(运维护栏)。周期抓取币安 API CHANGELOG,哈希比对,
变动时触发「API文档变动」通知模板(跑马灯 + 飞书)。状态写 Redis 供 admin dashboard 展示。
首次运行只记基线不告警。"""
import asyncio
import hashlib
import json
import logging
import time

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.db.session import SessionLocal
from app.db.models_notify import NotificationTemplate
from app.services.notifier import fire_template

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "API文档变动"
CHECK_INTERVAL = 6 * 3600   # 6h
# 监控源:币安现货 API 文档 CHANGELOG(raw markdown,稳定可哈希、变动=真实接口更新)。
# dict 可扩展更多源;取不到的源静默跳过,不影响其它。
DOC_SOURCES = {
    "币安现货API": "https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/CHANGELOG.md",
}


def ensure_doc_template(db) -> None:
    """幂等播种「API文档变动」通知模板,使其出现在 /admin/notifications 可编辑。"""
    exists = db.query(NotificationTemplate).filter(
        NotificationTemplate.template_name == TEMPLATE_NAME,
    ).first()
    if exists:
        return
    db.add(NotificationTemplate(
        template_name=TEMPLATE_NAME,
        category="system",
        title_template="⚠ 币安API文档变动",
        content_template="检测到 {source} 文档更新({time}),请核对接口/参数变更: {url}",
        enable_feishu=True,
        enable_email=False,
        enable_marquee=True,
        priority=1,
        cooldown_seconds=3600,
        marquee_color="#ef4444",
        marquee_blink=True,
        sound_key="none",
        is_enabled=True,
    ))
    db.commit()
    logger.info("Seeded notification template: API文档变动")


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


class DocChecker:
    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._running = False

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True
        asyncio.create_task(self._loop())
        logger.info("DocChecker started")

    async def stop(self):
        self._running = False

    async def _loop(self):
        await asyncio.sleep(20)  # 启动后稍候,避开启动风暴
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                logger.warning(f"DocChecker error: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

    async def _check_all(self):
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
            for name, url in DOC_SOURCES.items():
                try:
                    resp = await c.get(url)
                    if resp.status_code != 200:
                        logger.debug(f"DocChecker {name} HTTP {resp.status_code}")
                        continue
                    h = hashlib.sha256(resp.text.encode("utf-8", "ignore")).hexdigest()
                except Exception as e:
                    logger.debug(f"DocChecker fetch {name} failed: {e}")
                    continue
                key = f"docchecker:hash:{name}"
                prev = await self._redis.get(key)
                await self._redis.set(key, h)
                await self._redis.set("docchecker:last_check", str(int(time.time())))
                if prev and prev != h:
                    logger.warning(f"Binance API doc changed: {name}")
                    await self._redis.set("docchecker:last_change",
                                          json.dumps({"source": name, "ts": int(time.time())}))
                    await asyncio.to_thread(fire_template, TEMPLATE_NAME,
                                            {"source": name, "url": url, "time": _now_str()})


doc_checker = DocChecker()
