import hashlib
import hmac
import base64
import json
import time
import logging
from decimal import Decimal

import httpx
import redis

from app.config import settings
from app.db.models import FeishuConfig
from app.db.models_notify import NotificationLog, NotificationTemplate
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


class FeishuSender:
    def __init__(self):
        self._webhook_url: str | None = None
        self._secret_key: str | None = None
        self._alert_interval: int = 5
        self._alert_count: int = 1
        self._enable_transfer_fail: bool = True
        self._enable_new_borrow: bool = True
        self._last_reload = 0
        self._rate_limiter: dict[str, list[float]] = {}
        self._template_cache: dict[str, dict] = {}
        self._template_reload = 0

    def _ensure_config(self):
        now = time.time()
        if now - self._last_reload < 300 and self._webhook_url is not None:
            return
        db = SessionLocal()
        try:
            cfg = db.query(FeishuConfig).first()
            if cfg:
                self._webhook_url = cfg.webhook_url
                self._secret_key = cfg.secret_key
                self._alert_interval = cfg.alert_interval_sec or 5
                self._alert_count = cfg.alert_count or 1
                self._enable_transfer_fail = cfg.enable_transfer_fail_alert
                self._enable_new_borrow = cfg.enable_new_borrow_alert
            self._last_reload = now
        finally:
            db.close()

    def _load_templates(self):
        now = time.time()
        if now - self._template_reload < 300 and self._template_cache:
            return
        db = SessionLocal()
        try:
            templates = db.query(NotificationTemplate).filter(NotificationTemplate.is_enabled == True).all()
            self._template_cache = {
                t.template_name: {
                    "enable_marquee": getattr(t, "enable_marquee", True),
                    "marquee_color": getattr(t, "marquee_color", "#3b82f6"),
                    "marquee_blink": getattr(t, "marquee_blink", False),
                    "sound_key": getattr(t, "sound_key", "none"),
                    "priority": t.priority,
                    "enable_email": t.enable_email,
                }
                for t in templates
            }
            self._template_reload = now
        finally:
            db.close()

    def _check_rate_limit(self, alert_type: str) -> bool:
        now = time.time()
        history = self._rate_limiter.get(alert_type, [])
        cutoff = now - self._alert_interval
        history = [t for t in history if t > cutoff]
        if len(history) >= self._alert_count:
            return False
        history.append(now)
        self._rate_limiter[alert_type] = history
        return True

    def _write_log(self, template_name: str, channel: str, status: str, content: str):
        try:
            db = SessionLocal()
            db.add(NotificationLog(
                template_name=template_name, channel=channel,
                status=status, content=content[:500],
            ))
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"Failed to write notification log: {e}")

    def _broadcast_marquee(self, template_name: str, title: str, content: str):
        self._load_templates()
        tpl = self._template_cache.get(template_name, {})
        if not tpl.get("enable_marquee", True):
            return
        payload = {
            "title": title,
            "content": content,
            "priority": tpl.get("priority", 2),
            "color": tpl.get("marquee_color", "#3b82f6"),
            "blink": tpl.get("marquee_blink", False),
            "sound": tpl.get("sound_key", "none"),
        }
        try:
            r = _get_redis()
            r.publish("notification:broadcast", json.dumps(payload))
        except Exception as e:
            logger.warning(f"Redis marquee broadcast failed: {e}")

    async def send(self, title: str, content: str, template_name: str | None = None):
        self._ensure_config()
        if not self._webhook_url:
            return

        payload: dict = {
            "msg_type": "text",
            "content": {"text": f"[{title}]\n{content}"},
        }

        if self._secret_key:
            ts = str(int(time.time()))
            string_to_sign = f"{ts}\n{self._secret_key}"
            sign = base64.b64encode(
                hmac.new(string_to_sign.encode(), b"", hashlib.sha256).digest()
            ).decode()
            payload["timestamp"] = ts
            payload["sign"] = sign

        status = "sent"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._webhook_url, json=payload)
                if resp.status_code != 200:
                    logger.warning(f"Feishu send failed: HTTP {resp.status_code}")
                    status = "failed"
        except Exception as e:
            logger.warning(f"Feishu send error: {e}")
            status = "failed"

        tpl_name = template_name or title
        self._write_log(tpl_name, "feishu", status, content)
        self._broadcast_marquee(tpl_name, title, content)

    async def notify_position_opened(self, account_note: str, symbol: str, spread: Decimal, qty: Decimal, usdt: Decimal):
        self._ensure_config()
        if not self._enable_new_borrow:
            return
        if not self._check_rate_limit("new_borrow"):
            return
        await self.send(
            "量化系统-新增借币",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"方向: 杠杆借币做空 + 合约做多\n"
            f"数量: {qty}\n"
            f"金额: {usdt} USDT\n"
            f"点差: {spread}%",
            template_name="开仓通知",
        )

    async def notify_position_closed(self, account_note: str, symbol: str, pnl: Decimal, spread: Decimal):
        if not self._check_rate_limit("close"):
            return
        emoji = "+" if pnl >= 0 else ""
        await self.send(
            "量化系统-平仓通知",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"盈亏: {emoji}{pnl} USDT\n"
            f"平仓点差: {spread}%",
            template_name="平仓通知",
        )

    async def notify_error(self, account_note: str, action: str, error: str):
        if not self._check_rate_limit("error"):
            return
        await self.send(
            "量化系统-下单失败",
            f"账户: {account_note}\n"
            f"操作: {action}\n"
            f"错误: {error}",
            template_name="异常仓位",
        )

    async def notify_anomaly(self, account_note: str, symbol: str, position_id: int, detail: str):
        await self.send(
            "量化系统-异常仓位",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"仓位ID: {position_id}\n"
            f"状态: ANOMALY — 回滚失败\n"
            f"详情: {detail}\n"
            f"请立即人工介入处理!",
            template_name="异常仓位",
        )

    async def notify_risk(self, account_note: str, margin_level: Decimal):
        if not self._check_rate_limit("risk"):
            return
        await self.send(
            "量化系统-风险提醒",
            f"账户: {account_note}\n"
            f"保证金水平: {margin_level}\n"
            f"请立即检查!",
            template_name="风控告警",
        )

    async def notify_transfer_fail(self, account_note: str, direction: str, amount: Decimal, error: str):
        self._ensure_config()
        if not self._enable_transfer_fail:
            return
        if not self._check_rate_limit("transfer_fail"):
            return
        await self.send(
            "量化系统-划转失败",
            f"类型: 自动划转\n"
            f"账户: {account_note}\n"
            f"方向: {direction}\n"
            f"金额: {amount} USDT\n"
            f"错误: {error}",
            template_name="划转失败",
        )

    async def notify_margin_rate(self, account_note: str, current_rate: Decimal, threshold: Decimal):
        if not self._check_rate_limit("margin_rate"):
            return
        await self.send(
            "量化系统-风险提醒",
            f"类型: 合约爆仓率预警\n"
            f"账户: {account_note}\n"
            f"当前爆仓率: {current_rate}%\n"
            f"预警阈值: {threshold}%",
            template_name="爆仓率预警",
        )

    async def notify_leverage_risk(self, account_note: str, risk_value: Decimal, threshold: Decimal, margin: Decimal, available: Decimal):
        if not self._check_rate_limit("leverage_risk"):
            return
        await self.send(
            "量化系统-风险提醒",
            f"类型: 子账户杠杆风险预警\n"
            f"账户: {account_note}\n"
            f"当前风险值: {risk_value}\n"
            f"预警阈值: {threshold}\n"
            f"保证金: {margin} USDT\n"
            f"可用余额: {available} USDT",
            template_name="杠杆风险预警",
        )
