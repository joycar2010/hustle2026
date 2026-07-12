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

from .feishu import send_bot_chat, send_bot_text, send_webhook_text
from .throttle import throttle_ok

logger = logging.getLogger(__name__)


@dataclass
class FeishuTarget:
    webhook_url: str = ""
    app_id: str = ""
    app_secret: str = ""
    open_id: str = ""
    chat_id: str = ""


def feishu_from_env() -> "FeishuTarget":
    """从标准环境变量装配告警目标(webhook/自建应用 bot open_id 或 chat_id)。"""
    import os
    return FeishuTarget(
        webhook_url=os.environ.get("DCM_FEISHU_WEBHOOK", ""),
        app_id=os.environ.get("DCM_FEISHU_APP_ID", ""),
        app_secret=os.environ.get("DCM_FEISHU_APP_SECRET", ""),
        open_id=os.environ.get("DCM_FEISHU_OPEN_ID", ""),
        chat_id=os.environ.get("DCM_FEISHU_CHAT_ID", ""),
    )


CONFIG_KEY = "dcm:notify:config"      # mixadmin 通知模块写入的全局节流配置(权威=mix_main,此键=分发)
_CFG_CACHE: dict = {"ts": 0.0, "cfg": None}
_CFG_TTL = 60.0


def _global_config(redis_url: str) -> dict | None:
    """读全局通知配置(60s 进程内缓存;fatal 300s/1 硬地板不受其影响)。失败=None 用构造参数。"""
    import time as _t
    if _t.monotonic() - _CFG_CACHE["ts"] < _CFG_TTL:
        return _CFG_CACHE["cfg"]
    cfg = None
    try:
        r = redis_sync.from_url(redis_url, decode_responses=True,
                                socket_timeout=2, socket_connect_timeout=2)
        raw = r.get(CONFIG_KEY)
        r.close()
        if raw:
            cfg = json.loads(raw)
    except Exception:  # noqa: BLE001
        cfg = None
    _CFG_CACHE.update(ts=_t.monotonic(), cfg=cfg)
    return cfg


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
        """发一条通知。key 用于节流分桶(自动加 service 前缀)。
        level=fatal 不绕过节流而是用 300s/1 硬地板——完全绕过曾造成巡检循环每 30s 重发同一致命告警
        (告警风暴淹没真信号);300s 地板保证致命级最多被压制 5 分钟,不会被长节流吞掉。
        非 fatal 节流参数优先用 dcm:notify:config 全局配置(mixadmin 通知模块热下发),无则构造参数。"""
        results: dict = {}
        tkey = f"{self.service}:{key}"
        if level == "fatal":
            if not throttle_ok(self.redis_url, f"{tkey}:fatal", 300, 1):
                return {"throttled": True}
        else:
            g = _global_config(self.redis_url) or {}
            interval = int(g.get("interval_sec") or self.throttle_interval_sec)
            max_cnt = int(g.get("max_count") or self.throttle_max_count)
            if not throttle_ok(self.redis_url, tkey, interval, max_cnt):
                return {"throttled": True}

        if self.feishu.webhook_url:
            ok, detail = send_webhook_text(self.feishu.webhook_url, f"{self.service}|{title}", content)
            results["feishu_webhook"] = detail if not ok else "sent"
        if self.feishu.app_id and self.feishu.chat_id:
            ok, detail = send_bot_chat(self.feishu.app_id, self.feishu.app_secret,
                                       self.feishu.chat_id, f"{self.service}|{title}", content)
            results["feishu_chat"] = detail if not ok else "sent"
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
