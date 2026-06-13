"""按模板名渲染并分发通知(跑马灯 + 飞书 webhook)。后台任务(如 DocChecker)可直接调用。
复用 admin /notifications 的 NotificationTemplate 体系:enable_marquee → notification:broadcast;
enable_feishu → 全局 FeishuConfig(user_id=None)的 webhook。"""
import json
import logging

import httpx
import redis as redis_sync

from app.config import settings
from app.db.session import SessionLocal
from app.db.models_notify import NotificationTemplate, NotificationLog
from app.db.models import FeishuConfig

logger = logging.getLogger(__name__)


def fire_template(template_name: str, variables: dict | None = None) -> dict:
    """渲染并发送指定模板(同步;后台 async 任务用 asyncio.to_thread 调)。模板缺失或停用则跳过。"""
    variables = variables or {}
    db = SessionLocal()
    results: dict = {}
    try:
        t = db.query(NotificationTemplate).filter(
            NotificationTemplate.template_name == template_name,
            NotificationTemplate.is_enabled == True,  # noqa: E712
        ).first()
        if not t:
            return {"skipped": "template missing or disabled"}

        title = t.title_template or t.template_name
        content = t.content_template or title
        for k, v in variables.items():
            title = title.replace("{{" + k + "}}", str(v)).replace("{" + k + "}", str(v))
            content = content.replace("{{" + k + "}}", str(v)).replace("{" + k + "}", str(v))

        if getattr(t, "enable_marquee", True):
            try:
                r = redis_sync.from_url(settings.redis_url, decode_responses=True)
                r.publish("notification:broadcast", json.dumps({
                    "title": title, "content": content, "priority": t.priority,
                    "color": getattr(t, "marquee_color", "#3b82f6"),
                    "blink": getattr(t, "marquee_blink", False),
                    "sound": getattr(t, "sound_key", "none"),
                }))
                r.close()
                results["marquee"] = "sent"
                db.add(NotificationLog(template_name=t.template_name, channel="marquee",
                                       status="sent", content=content[:500]))
            except Exception as e:
                results["marquee"] = f"error: {e}"

        if getattr(t, "enable_feishu", False):
            fc = db.query(FeishuConfig).filter(FeishuConfig.user_id.is_(None)).first()
            if fc and fc.webhook_url:
                try:
                    resp = httpx.post(fc.webhook_url,
                                      json={"msg_type": "text", "content": {"text": f"{title}\n{content}"}},
                                      timeout=10)
                    ok = resp.status_code == 200
                    results["feishu"] = "sent" if ok else f"http {resp.status_code}"
                    db.add(NotificationLog(template_name=t.template_name, channel="feishu",
                                           status="sent" if ok else "failed", content=content[:500]))
                except Exception as e:
                    results["feishu"] = f"error: {e}"
            else:
                results["feishu"] = "skipped: 飞书 webhook 未配置"

        db.commit()
    finally:
        db.close()
    logger.info(f"fire_template[{template_name}] -> {results}")
    return results
