"""Proxy IP expiry checker — daily check + Feishu alert 7 days before expiry."""
import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.models.account import Account
from app.models.user import User

logger = logging.getLogger(__name__)

# 已通知记录，避免同一天重复发送（key: account_id, value: date）
_notified_today: dict[str, date] = {}


class ProxyExpiryChecker:
    """每天检查代理IP过期时间，提前7天飞书通知管理员。"""

    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.interval = 3600  # 每小时检查一次
        self.warn_days = 7    # 过期前多少天开始提醒

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())
        logger.info("ProxyExpiryChecker started (interval: 1h, warn: 7d)")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("ProxyExpiryChecker stopped")

    async def _loop(self):
        # 启动后等待60秒再开始第一次检查
        await asyncio.sleep(60)
        while self.running:
            try:
                await self._check_all()
            except Exception as e:
                logger.error(f"ProxyExpiryChecker error: {e}")
            await asyncio.sleep(self.interval)

    async def _check_all(self):
        today = date.today()
        async with AsyncSessionLocal() as db:
            # 查所有有 proxy_config 的活跃账户
            result = await db.execute(
                select(Account).where(
                    Account.is_active == True,
                    Account.proxy_config.isnot(None),
                )
            )
            accounts = result.scalars().all()

            for account in accounts:
                cfg = account.proxy_config
                if not cfg or not isinstance(cfg, dict):
                    continue
                expires_str = cfg.get("expires_at")
                if not expires_str:
                    continue

                try:
                    expires = date.fromisoformat(str(expires_str)[:10])
                except (ValueError, TypeError):
                    continue

                days_left = (expires - today).days
                aid = str(account.account_id)

                # 已过期 → 更新状态
                if days_left < 0:
                    if cfg.get("ip_status") != "expired":
                        cfg["ip_status"] = "expired"
                        await db.execute(
                            update(Account)
                            .where(Account.account_id == account.account_id)
                            .values(proxy_config=cfg)
                        )
                        await db.commit()
                    await self._notify(db, account, days_left, "expired")

                # 7天内到期 → 提醒
                elif days_left <= self.warn_days:
                    await self._notify(db, account, days_left, "warning")

                # 正常 → 确保状态为 active
                elif cfg.get("ip_status") != "active":
                    cfg["ip_status"] = "active"
                    await db.execute(
                        update(Account)
                        .where(Account.account_id == account.account_id)
                        .values(proxy_config=cfg)
                    )
                    await db.commit()

    async def _notify(self, db, account: Account, days_left: int, level: str):
        """发飞书通知给所有管理员角色用户。"""
        aid = str(account.account_id)
        today = date.today()

        # 每天每个账户只通知一次
        if _notified_today.get(aid) == today:
            return
        _notified_today[aid] = today

        # 清理旧日期记录
        for k in list(_notified_today):
            if _notified_today[k] < today:
                del _notified_today[k]

        cfg = account.proxy_config or {}
        ip = cfg.get("host", "未知")
        expires = cfg.get("expires_at", "未知")
        region = cfg.get("region", "")

        if level == "expired":
            title = "⚠️ 代理IP已过期"
            color = "red"
            body = (
                f"账户: {account.account_name}\n"
                f"代理IP: {ip} ({region})\n"
                f"过期日期: {expires}\n"
                f"已过期 {abs(days_left)} 天，请立即续费或更换代理IP！"
            )
        else:
            title = "⏰ 代理IP即将过期"
            color = "orange"
            body = (
                f"账户: {account.account_name}\n"
                f"代理IP: {ip} ({region})\n"
                f"过期日期: {expires}\n"
                f"剩余 {days_left} 天，请及时续费避免交易中断。"
            )

        # 获取所有管理员
        admin_result = await db.execute(
            select(User).where(
                User.is_active == True,
                User.role.in_(["超级管理员", "系统管理员", "管理员"]),
            )
        )
        admins = admin_result.scalars().all()

        try:
            from app.services.feishu_service import get_feishu_service
            feishu = get_feishu_service()
            if not feishu:
                logger.warning("Feishu service not initialized, skip proxy expiry alert")
                return

            for admin in admins:
                if not admin.feishu_open_id:
                    continue
                try:
                    await feishu.send_card_message(
                        receive_id=admin.feishu_open_id,
                        title=title,
                        content=body,
                        color=color,
                    )
                    logger.info(f"Proxy expiry alert sent to {admin.username} for {account.account_name}")
                except Exception as e:
                    logger.error(f"Failed to send proxy expiry alert to {admin.username}: {e}")
        except Exception as e:
            logger.error(f"Feishu proxy alert failed: {e}")


proxy_expiry_checker = ProxyExpiryChecker()
