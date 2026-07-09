"""无 ORM 的通知分发:节流 → 飞书(webhook / 自建应用 bot) → 跑马灯(Redis publish)。

设计约束(coin 告警双轨收敛的教训):
- 所有服务共用本模块 + 同一 Redis 令牌桶键空间(dcm:throttle:),节流口径统一;
- key 按 service:类型 组织,跨服务不互吞;
- 致命级(level="fatal")绕过节流,永不抑制;
- 模板/落库存储是 gateway 的事,本模块只做发送,保持零 DB 依赖。

同步实现;asyncio 调用方用 asyncio.to_thread(notifier.fire, ...)。
"""
import json
import logging
from dataclasses import dataclass

import redis as redis_sync

from .feishu import send_bot_text, send_webhook_text
from .throttle import throttle_ok

logger = logging.getLogger(__name__)


@dataclass
class FeishuTarget:
    webhook_url: str = ""
    app_id: str = ""
    app_secret: str = ""
    open_id: str = ""


class Notifier:
    def __init__(self, redis_url: str, service: str,
                 feishu: FeishuTarget | None = None,
                 marquee_channel: str = "dcm:notify:broadcast",
                 throttle_interval_sec: int = 60, throttle_max_count: int = 3):
        self.redis_url = redis_url
        self.service = service
        self.feishu = feishu or FeishuTarget()
        self.marquee_channel = marquee_channel
        self.throttle_interval_sec = throttle_interval_sec
        self.throttle_max_count = throttle_max_count

    def fire(self, key: str, title: str, content: str,
             level: str = "info", marquee: bool = False,
             color: str = "#3b82f6", blink: bool = False) -> dict:
        """发一条通知。key 用于节流分桶(自动加 service 前缀);level=fatal 绕过节流。"""
        results: dict = {}
        tkey = f"{self.service}:{key}"
        if level != "fatal" and not throttle_ok(
                self.redis_url, tkey, self.throttle_interval_sec, self.throttle_max_count):
            return {"throttled": True}

        if self.feishu.webhook_url:
            ok, detail = send_webhook_text(self.feishu.webhook_url, f"{self.service}|{title}", content)
            results["feishu_webhook"] = detail if not ok else "sent"
        if self.feishu.app_id and self.feishu.open_id:
            ok, detail = send_bot_text(self.feishu.app_id, self.feishu.app_secret,
                                       self.feishu.open_id, f"{self.service}|{title}", content)
            results["feishu_bot"] = detail if not ok else "sent"

        if marquee:
            try:
                r = redis_sync.from_url(self.redis_url, decode_responses=True)
                r.publish(self.marquee_channel, json.dumps({
                    "service": self.service, "title": title, "content": content,
                    "level": level, "color": color, "blink": blink,
                }, ensure_ascii=False))
                r.close()
                results["marquee"] = "sent"
            except Exception as e:
                results["marquee"] = f"error: {e}"

        logger.info(f"notify[{self.service}:{key}] {level} -> {results}")
        return results
