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
        self._last_reload = 0

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
            self._last_reload = now
        finally:
            db.close()

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
        await self.send(
            "开仓通知",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"方向: 杠杆借币做空 + 合约做多\n"
            f"数量: {qty}\n"
            f"金额: {usdt} USDT\n"
            f"点差: {spread}%",
        )

    async def notify_position_closed(self, account_note: str, symbol: str, pnl: Decimal, spread: Decimal):
        emoji = "+" if pnl >= 0 else ""
        await self.send(
            "平仓通知",
            f"账户: {account_note}\n"
            f"币种: {symbol}\n"
            f"盈亏: {emoji}{pnl} USDT\n"
            f"平仓点差: {spread}%",
        )

    async def notify_error(self, account_note: str, action: str, error: str):
        await self.send(
            "错误告警",
            f"账户: {account_note}\n"
            f"操作: {action}\n"
            f"错误: {error}",
        )

    async def notify_risk(self, account_note: str, margin_level: Decimal):
        await self.send(
            "风险告警",
            f"账户: {account_note}\n"
            f"保证金水平: {margin_level}\n"
            f"请立即检查!",
        )
