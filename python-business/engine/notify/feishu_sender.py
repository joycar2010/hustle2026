import hashlib
import hmac
import base64
import time
import logging
from decimal import Decimal

import httpx

from app.db.models import FeishuConfig
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


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

    async def send(self, title: str, content: str):
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

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._webhook_url, json=payload)
                if resp.status_code != 200:
                    logger.warning(f"Feishu send failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Feishu send error: {e}")

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
        )

    async def notify_error(self, account_note: str, action: str, error: str):
        if not self._check_rate_limit("error"):
            return
        await self.send(
            "量化系统-下单失败",
            f"账户: {account_note}\n"
            f"操作: {action}\n"
            f"错误: {error}",
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
        )

    async def notify_risk(self, account_note: str, margin_level: Decimal):
        if not self._check_rate_limit("risk"):
            return
        await self.send(
            "量化系统-风险提醒",
            f"账户: {account_note}\n"
            f"保证金水平: {margin_level}\n"
            f"请立即检查!",
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
        )
