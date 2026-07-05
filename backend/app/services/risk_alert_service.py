"""
风险控制提醒服务
Risk Control Alert Service

处理各类风险控制提醒：
- MT5连接状态监控
- 净资产监控（Binance/Bybit）
- 爆仓价监控（Binance/Bybit）
- 单腿持仓监控

使用"生鲜配送语"发送通知
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.models.notification_config import NotificationTemplate
from app.services.feishu_service import get_feishu_service
from app.services.alert_bus import alert_bus, Severity
from app.models.notification_config import NotificationConfig
from app.websocket.manager import manager
import time

logger = logging.getLogger(__name__)


def get_beijing_time():
    """Get current time in Beijing timezone (UTC+8) as naive datetime"""
    beijing_tz = ZoneInfo("Asia/Shanghai")
    beijing_time = datetime.now(beijing_tz)
    return beijing_time.replace(tzinfo=None)


class _SafeDict(dict):
    """format_map() helper: missing keys are kept as literal {key} placeholders."""
    def __missing__(self, key):
        return '{' + key + '}'


class RiskAlertService:
    """风险控制提醒服务"""

    # Class-level cooldown cache shared across all instances
    _cooldown_cache: Dict[str, datetime] = {}
    _funding_cache: Dict = {}  # {pair_code: {'data': ..., 'ts': ...}}
    _swap_cache: Dict = {}

    def __init__(self, db: AsyncSession):
        self.db = db

    @property
    def cooldown_cache(self) -> Dict[str, datetime]:
        return RiskAlertService._cooldown_cache

    async def _can_send_alert(
        self, user_id: str, template_key: str, cooldown_seconds: int = 60,
        dedup_suffix: str = None,
    ) -> bool:
        """Cross-process dedup via AlertBus (Redis SETNX EX). Falls back to
        the in-process cooldown_cache if Redis is down.
        dedup_suffix(2026-07-04): 多交易对隔离——附加到 dedup_key 使各 pair 独立冷却,
        否则多对共用一个模板冷却→一个对告警把其它对静默节流(跨对漏报)。默认None=原行为。"""
        if cooldown_seconds <= 0:
            return True
        _sfx = f":{dedup_suffix}" if dedup_suffix else ""
        dedup_key = f"alert:dedup:{user_id}:_:{template_key}{_sfx}"
        claimed = await alert_bus.try_dedup(dedup_key, cooldown_seconds)
        if not claimed:
            return False
        # Mirror to local cache for legacy diagnostics — not authoritative.
        self.cooldown_cache[f"{user_id}_{template_key}"] = get_beijing_time()
        return True

    async def _send_alert(
        self,
        user_id: str,
        template_key: str,
        variables: Dict[str, any],
        dedup_suffix: str = None,
    ) -> bool:
        """发送提醒通知。dedup_suffix(2026-07-04): 透传给冷却去重, 多交易对 per-pair 隔离。"""
        try:
            logger.info(f"[RISK_ALERT] Starting to send risk alert: user_id={user_id}, template_key={template_key}, variables={variables}")
            # 获取模板
            result = await self.db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.template_key == template_key
                )
            )
            template = result.scalar_one_or_none()

            if not template:
                logger.error(f"Template not found: {template_key}")
                return False

            # 检查模板是否启用 (is_active)
            if not template.is_active:
                logger.debug(f"Template {template_key} is disabled (is_active=False), skipping")
                return False

            # 检查飞书渠道是否启用 (enable_feishu)
            if not template.enable_feishu:
                logger.debug(f"Template {template_key} Feishu channel disabled (enable_feishu=False), skipping")
                return False

            # 检查冷却时间
            if not await self._can_send_alert(
                user_id, template_key, template.cooldown_seconds,
                dedup_suffix=dedup_suffix,
            ):
                logger.debug(
                    f"Alert {template_key} for user {user_id} is in cooldown"
                )
                return False

            # 检查用户登录状态（仅对特定提醒类型）
            # 无条件触发的提醒类型（净资产、点差提醒）
            always_send_templates = {
                'binance_net_asset_alert',
                'bybit_net_asset_alert',
                'total_net_asset_alert',
                'forward_open_spread_alert',
                'forward_close_spread_alert',
                'reverse_open_spread_alert',
                'reverse_close_spread_alert',
                'binance_ip_ban_alert',  # IP封禁无论用户在不在线都必须通知
            }

            # 所有风控告警无条件发送（前端连Go WS，Python ws_manager始终为空）
            # 获取用户信息和飞书配置
            from app.models.user import User
            import uuid as uuid_lib
            result = await self.db.execute(
                select(User).where(User.user_id == uuid_lib.UUID(user_id))
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.debug(f"User not found: {user_id}")
                return False

            # 检查用户通知偏好设置
            from sqlalchemy import text as _text
            notif_row = (await self.db.execute(
                _text("SELECT feishu_enabled, enable_risk_notifications FROM user_notification_settings WHERE user_id = CAST(:uid AS UUID)"),
                {"uid": user_id}
            )).first()
            if notif_row:
                feishu_enabled, enable_risk = notif_row[0], notif_row[1]
                if feishu_enabled is False:
                    logger.debug(f"User {user_id} has feishu disabled in notification settings")
                    return False
                risk_templates = {
                    'binance_net_asset_alert', 'bybit_net_asset_alert', 'total_net_asset_alert',
                    'binance_liquidation_alert', 'bybit_liquidation_alert',
                    'forward_open_spread_alert', 'forward_close_spread_alert',
                    'reverse_open_spread_alert', 'reverse_close_spread_alert',
                    'single_leg_alert', 'mt5_lag_alert',
                }
                if template_key in risk_templates and enable_risk is False:
                    logger.debug(f"User {user_id} has risk notifications disabled")
                    return False

            # 检查用户是否配置了飞书
            if not user.email and not user.feishu_open_id:
                logger.debug(f"User {user_id} has no feishu configuration")
                return False

            # 检查全局飞书服务是否启用
            result = await self.db.execute(
                select(NotificationConfig).where(
                    NotificationConfig.service_type == "feishu"
                )
            )
            global_config = result.scalar_one_or_none()

            if not global_config or not global_config.is_enabled:
                logger.debug(f"Feishu service not enabled globally")
                return False

            # 使用传入的variables（已包含实时账户数据）
            # 确保必要的字段存在
            variables.setdefault('binance_balance', '0.00')
            variables.setdefault('bybit_balance', '0.00')
            variables.setdefault('total_assets', '0.00')

            # Log variables for debugging (logger handles encoding properly)
            logger.info(f"[RISK_ALERT] Variables for template {template_key}: {variables}")

            # 格式化消息（safe format：缺失变量回退为占位符而不是抛 KeyError）
            _vars = _SafeDict(variables)
            title = template.title_template.format_map(_vars)
            content = template.content_template.format_map(_vars)

            # Message formatted successfully
            logger.info(f"[RISK_ALERT] Message formatted successfully for template {template_key}")

            # 获取飞书服务
            feishu = get_feishu_service()
            feishu_success = False
            if not feishu:
                logger.warning("Feishu service not initialized, will still broadcast to frontend")

            # 根据优先级设置颜色
            color_map = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
            color = color_map.get(template.priority, "orange")

            # 确定接收者ID（优先使用飞书open_id）
            receiver_id = user.feishu_open_id if user.feishu_open_id else user.email
            receive_id_type = "open_id" if user.feishu_open_id else "email"

            # 发送飞书卡片消息
            if feishu:
                try:
                    logger.info(f"[RISK_ALERT] Preparing to send Feishu card: receiver_id={receiver_id}, title={title}")
                    result = await feishu.send_card_message(
                        receive_id=receiver_id,
                        title=title,
                        content=content,
                        receive_id_type=receive_id_type,
                        color=color
                    )
                    feishu_success = result.get("success", False)
                    logger.info(f"[RISK_ALERT] Feishu card send result: success={feishu_success}, result={result}")
                except Exception as _fe:
                    logger.warning(f"[RISK_ALERT] Feishu send failed: {_fe}")
                    feishu_success = False

            # 更新冷却时间（无论飞书是否成功，只要通过了 dedup 就更新）
            cache_key = f"{user_id}_{template_key}"
            self.cooldown_cache[cache_key] = get_beijing_time()

            if feishu_success:
                logger.info(f"Alert sent via Feishu: {template_key} to user {user_id}")

            # Mirror to unified AlertBus ledger — best effort
            try:
                severity = {1: Severity.INFO, 2: Severity.INFO,
                            3: Severity.WARN, 4: Severity.DANGER}.get(
                    template.priority, Severity.WARN)
                await alert_bus.persist(
                    user_id=user_id,
                    template_key=template_key,
                    severity=severity,
                    title=title,
                    message=content,
                    payload=dict(variables) if variables else {},
                    feishu_sent=feishu_success,
                )
            except Exception as _be:
                logger.debug(f"[risk_alert] AlertBus persist skipped: {_be}")

            # 发送邮件（如果模板启用了邮件渠道且用户有邮箱）
            if template.enable_email and user.email:
                try:
                    from app.services.email_service import email_service as _es
                    _plain = content.replace("**", "")
                    await _es.send_alert_email(self.db, user.email, title, _plain)
                except Exception as _ee:
                    logger.warning(f"[RISK_ALERT] Email failed: {_ee}")

            # 通过WebSocket推送到前端（无论飞书是否成功都推送弹窗）
            await self._broadcast_alert_to_frontend(
                user_id=user_id,
                template_key=template_key,
                template=template,
                variables=variables
            )

            return feishu_success or True

        except Exception as e:
            logger.error(f"Error sending alert {template_key}: {e}", exc_info=True)
            return False

    async def _broadcast_alert_to_frontend(
        self,
        user_id: str,
        template_key: str,
        template: NotificationTemplate,
        variables: Dict[str, any]
    ):
        """通过WebSocket广播提醒到前端"""
        try:
            # 映射模板Key到前端Alert Type
            alert_type_map = {
                'forward_open_spread_alert': 'forward_open',
                'forward_close_spread_alert': 'forward_close',
                'reverse_open_spread_alert': 'reverse_open',
                'reverse_close_spread_alert': 'reverse_close',
                'mt5_lag_alert': 'mt5_lag',
                'binance_net_asset_alert': 'binance_asset',
                'bybit_net_asset_alert': 'bybit_asset',
                'total_net_asset_alert': 'total_asset',
                'binance_liquidation_alert': 'binance_liquidation',
                'bybit_liquidation_alert': 'bybit_liquidation',
                'single_leg_alert': 'single_leg_alert',
                'binance_ip_ban_alert': 'binance_ip_ban',
            }

            alert_type = alert_type_map.get(template_key, template_key)

            # 映射优先级到前端level
            level_map = {
                1: 'info',
                2: 'info',
                3: 'warning',
                4: 'critical'
            }

            # 构造前端提醒消息
            alert_message = {
                "type": "risk_alert",
                "data": {
                    "alert_type": alert_type,
                    "level": level_map.get(template.priority, 'warning'),
                    "title": template.title_template.format(**variables),
                    "message": template.content_template.format(**variables),
                    "timestamp": get_beijing_time().isoformat(),
                    "template_key": template_key,
                    # 添加弹窗配置
                    "popup_config": {
                        "title": template.popup_title_template.format_map(_SafeDict(variables)) if template.popup_title_template else template.title_template.format_map(_SafeDict(variables)),
                        "content": template.popup_content_template.format_map(_SafeDict(variables)) if template.popup_content_template else template.content_template.format_map(_SafeDict(variables)),
                        "sound_file": template.alert_sound_file if template.alert_sound_file else '/sounds/hello-moto.mp3',
                        "sound_repeat": template.alert_sound_repeat if template.alert_sound_repeat else 3
                    }
                }
            }

            # ── Bridge to Go WebSocket Hub via Redis ──────────────────────
            # Python ws_manager.active_connections is empty (frontend connects to Go /ws,
            # not Python /api/v1/ws). Must publish through ws:user_event channel so the
            # Go RedisBridge forwards via Hub.SendToUser() to the actual client.
            try:
                from app.core.redis_client import redis_client as _rc
                import json as _json
                evt = {
                    "user_id": user_id,
                    "type": alert_message["type"],
                    "data": alert_message["data"],
                }
                await _rc.publish("ws:user_event", _json.dumps(evt))
            except Exception as bridge_err:
                logger.warning(f"[RISK_ALERT] Redis WS publish failed: {bridge_err}")

            # Legacy Python WS manager call kept as no-op fallback for any internal
            # consumers that may still subscribe via Python /api/v1/ws (none today).
            await manager.send_to_user(
                message=alert_message,
                user_id=user_id
            )

            # ── Stream hub: per-user alerts channel for Python /api/v1/ws clients ──
            try:
                from app.websocket.stream_hub import stream_hub
                await stream_hub.publish(f"alerts.{user_id}", alert_message["data"])
            except Exception as _se:
                logger.debug(f"[RISK_ALERT] stream publish (trader self) failed: {_se}")

            # ── Fan-out to subscribers (admins watching this trader) ──
            # Each subscriber receives the same payload via their own alerts.{uid}
            # channel + Redis bridge so they get popup + Go-WS too.
            try:
                from sqlalchemy import text as _text
                sub_rows = (await self.db.execute(_text(
                    "SELECT DISTINCT subscriber_user_id FROM notification_subscriptions "
                    "WHERE trader_user_id = CAST(:uid AS UUID) "
                    "AND template_id = CAST(:tid AS UUID) "
                    "AND is_enabled = true"
                ), {"uid": user_id, "tid": str(template.template_id)})).fetchall()
                from app.websocket.stream_hub import stream_hub
                from app.core.redis_client import redis_client as _rc
                import json as _json
                for sub in sub_rows:
                    sid = str(sub[0])
                    if sid == user_id:
                        continue  # already sent to self above
                    try:
                        await stream_hub.publish(f"alerts.{sid}", alert_message["data"])
                    except Exception:
                        pass
                    try:
                        await _rc.publish("ws:user_event", _json.dumps({
                            "user_id": sid,
                            "type": alert_message["type"],
                            "data": alert_message["data"],
                        }))
                    except Exception:
                        pass
            except Exception as _fe:
                logger.debug(f"[RISK_ALERT] subscriber fan-out failed: {_fe}")

            logger.info(f"Alert broadcasted to frontend: {template_key} for user {user_id}")

        except Exception as e:
            logger.error(f"Error broadcasting alert to frontend: {e}")

    # ========================================================================
    # MT5连接状态监控
    # ========================================================================

    async def check_mt5_lag(
        self, user_id: str, failure_count: int, last_response_time: str
    ) -> bool:
        """
        检查MT5连接延迟

        Args:
            user_id: 用户ID
            failure_count: 连接失败次数
            last_response_time: 最后响应时间

        Returns:
            是否发送成功
        """
        if failure_count <= 0:
            return False

        from app.utils.trading_time import is_bybit_trading_hours
        is_open, market_message = is_bybit_trading_hours()

        if is_open:
            status_prefix = "[交易时段] MT5卡顿"
        else:
            status_prefix = f"[停市] {market_message}"

        return await self._send_alert(
            user_id=user_id,
            template_key="mt5_lag_alert",
            variables={
                "failure_count": failure_count,
                "last_response_time": f"{status_prefix} | {last_response_time}",
            },
        )

    # ========================================================================
    # Binance IP封禁告警
    # ========================================================================

    async def check_binance_ip_ban(
        self,
        user_id: str,
        ip: str,
        ban_until_ms: int,
        message: str,
    ) -> bool:
        """
        Binance IP被封禁时立即触发飞书消息+弹窗通知

        冷却时间：10分钟（同一IP封禁不重复轰炸）
        """
        from datetime import datetime
        ban_until_dt = datetime.fromtimestamp(ban_until_ms / 1000)
        beijing_time = ban_until_dt.strftime('%Y-%m-%d %H:%M:%S')

        now_ms = int(__import__('time').time() * 1000)
        remaining_ms = max(0, ban_until_ms - now_ms)
        remaining_minutes = remaining_ms // 60000
        remaining_seconds = (remaining_ms % 60000) // 1000
        remaining_str = f"{remaining_minutes}分钟{remaining_seconds}秒" if remaining_minutes > 0 else f"{remaining_seconds}秒"

        return await self._send_alert(
            user_id=user_id,
            template_key="binance_ip_ban_alert",
            variables={
                "ip": ip,
                "ban_until_time": beijing_time,
                "remaining_time": remaining_str,
            },
        )

    async def check_bybit_ip_ban(
        self, user_id: str, ip: str, ban_until_ms: int, message: str,
    ) -> bool:
        """Bybit IP 被封禁 → 立即推送"""
        from datetime import datetime
        ban_until_dt = datetime.fromtimestamp(ban_until_ms / 1000)
        beijing_time = ban_until_dt.strftime('%Y-%m-%d %H:%M:%S')
        now_ms = int(__import__('time').time() * 1000)
        remaining_ms = max(0, ban_until_ms - now_ms)
        rm, rs = remaining_ms // 60000, (remaining_ms % 60000) // 1000
        remaining_str = f"{rm}分钟{rs}秒" if rm > 0 else f"{rs}秒"
        return await self._send_alert(
            user_id=user_id, template_key="bybit_ip_ban_alert",
            variables={"ip": ip, "ban_until_time": beijing_time, "remaining_time": remaining_str},
        )

    async def check_gate_ip_ban(
        self, user_id: str, ip: str, ban_until_ms: int, message: str,
    ) -> bool:
        """Gate.io IP 被封禁 → 立即推送"""
        from datetime import datetime
        ban_until_dt = datetime.fromtimestamp(ban_until_ms / 1000)
        beijing_time = ban_until_dt.strftime('%Y-%m-%d %H:%M:%S')
        now_ms = int(__import__('time').time() * 1000)
        remaining_ms = max(0, ban_until_ms - now_ms)
        rm, rs = remaining_ms // 60000, (remaining_ms % 60000) // 1000
        remaining_str = f"{rm}分钟{rs}秒" if rm > 0 else f"{rs}秒"
        return await self._send_alert(
            user_id=user_id, template_key="gate_ip_ban_alert",
            variables={"ip": ip, "ban_until_time": beijing_time, "remaining_time": remaining_str},
        )

    async def check_okx_ip_ban(
        self, user_id: str, ip: str, ban_until_ms: int, message: str,
    ) -> bool:
        """OKX IP 被封禁 → 立即推送"""
        from datetime import datetime
        ban_until_dt = datetime.fromtimestamp(ban_until_ms / 1000)
        beijing_time = ban_until_dt.strftime('%Y-%m-%d %H:%M:%S')
        now_ms = int(__import__('time').time() * 1000)
        remaining_ms = max(0, ban_until_ms - now_ms)
        rm, rs = remaining_ms // 60000, (remaining_ms % 60000) // 1000
        remaining_str = f"{rm}分钟{rs}秒" if rm > 0 else f"{rs}秒"
        return await self._send_alert(
            user_id=user_id, template_key="okx_ip_ban_alert",
            variables={"ip": ip, "ban_until_time": beijing_time, "remaining_time": remaining_str},
        )

    # ========================================================================
    # 净资产监控
    # ========================================================================

    async def check_binance_net_asset(
        self,
        user_id: str,
        current_asset: float,
        threshold: float,
        is_below: bool = True,
    ) -> bool:
        """
        检查Binance净资产

        Args:
            user_id: 用户ID
            current_asset: 当前净资产
            threshold: 预警阈值
            is_below: True=低于阈值, False=高于阈值

        Returns:
            是否发送成功
        """
        status = "低于" if is_below else "高于"

        return await self._send_alert(
            user_id=user_id,
            template_key="binance_net_asset_alert",
            variables={
                "current_asset": f"{current_asset:.2f}",
                "threshold": f"{threshold:.2f}",
                "status": status,
            },
        )

    async def check_bybit_net_asset(
        self,
        user_id: str,
        current_asset: float,
        threshold: float,
        is_below: bool = True,
    ) -> bool:
        """
        检查Bybit净资产

        Args:
            user_id: 用户ID
            current_asset: 当前净资产
            threshold: 预警阈值
            is_below: True=低于阈值, False=高于阈值

        Returns:
            是否发送成功
        """
        status = "低于" if is_below else "高于"

        return await self._send_alert(
            user_id=user_id,
            template_key="bybit_net_asset_alert",
            variables={
                "current_asset": f"{current_asset:.2f}",
                "threshold": f"{threshold:.2f}",
                "status": status,
            },
        )

    async def check_total_net_asset(
        self,
        user_id: str,
        current_asset: float,
        threshold: float,
        is_below: bool = True,
    ) -> bool:
        """
        检查总净资产

        Args:
            user_id: 用户ID
            current_asset: 当前总净资产
            threshold: 预警阈值
            is_below: True=低于阈值, False=高于阈值

        Returns:
            是否发送成功
        """
        status = "低于" if is_below else "高于"

        return await self._send_alert(
            user_id=user_id,
            template_key="total_net_asset_alert",
            variables={
                "current_asset": f"{current_asset:.2f}",
                "threshold": f"{threshold:.2f}",
                "status": status,
            },
        )

    # ========================================================================
    # 爆仓价监控
    # ========================================================================

    async def check_binance_liquidation(
        self,
        user_id: str,
        current_price: float,
        liquidation_price: float,
        distance: float,
        status: str,
    ) -> bool:
        """
        检查Binance爆仓价

        Args:
            user_id: 用户ID
            current_price: 当前价格
            liquidation_price: 爆仓价
            distance: 距离爆仓价的差距
            status: 状态描述（如"接近安全线"）

        Returns:
            是否发送成功
        """
        return await self._send_alert(
            user_id=user_id,
            template_key="binance_liquidation_alert",
            variables={
                "current_price": f"{current_price:.2f}",
                "liquidation_price": f"{liquidation_price:.2f}",
                "distance": f"{distance:.2f}",
                "status": status,
            },
        )

    async def check_bybit_liquidation(
        self,
        user_id: str,
        current_price: float,
        liquidation_price: float,
        distance: float,
        status: str,
    ) -> bool:
        """
        检查Bybit爆仓价

        Args:
            user_id: 用户ID
            current_price: 当前价格
            liquidation_price: 爆仓价
            distance: 距离爆仓价的差距
            status: 状态描述（如"接近安全线"）

        Returns:
            是否发送成功
        """
        return await self._send_alert(
            user_id=user_id,
            template_key="bybit_liquidation_alert",
            variables={
                "current_price": f"{current_price:.2f}",
                "liquidation_price": f"{liquidation_price:.2f}",
                "distance": f"{distance:.2f}",
                "status": status,
            },
        )

    # ========================================================================
    # 单腿持仓监控
    # ========================================================================

    async def check_single_leg(
        self,
        user_id: str,
        exchange: str,
        quantity: float,
        duration: int,
        direction: str,
        binance_filled: float = 0,
        bybit_filled: float = 0,
        pair_code: str = None,
    ) -> bool:
        """
        检查单腿持仓

        Args:
            user_id: 用户ID
            exchange: 交易所名称（如"Binance"或"Bybit"）
            quantity: 单腿数量（未成交量）
            duration: 持续时间（秒）
            direction: 方向（"多头"或"空头"）
            binance_filled: Binance成交量
            bybit_filled: Bybit成交量

        Returns:
            是否发送成功
        """
        # 将交易所名称转换为生鲜配送语
        exchange_map = {
            "binance": "A仓库",
            "bybit": "B仓库",
            "mt5": "B仓库",
        }
        exchange_name = exchange_map.get(exchange.lower(), exchange)

        return await self._send_alert(
            user_id=user_id,
            template_key="single_leg_alert",
            variables={
                "exchange": exchange_name,
                "quantity": f"{quantity:.4f}",
                "duration": duration,
                "direction": direction,
                "binance_filled": f"{binance_filled:.4f}",
                "bybit_filled": f"{bybit_filled:.4f}",
                "unfilled_qty": f"{quantity:.4f}",
            },
            dedup_suffix=pair_code,  # 多交易对 per-pair 冷却隔离(2026-07-04)
        )

    # ========================================================================
    # 批量检查（用于定时任务）
    # ========================================================================

    async def check_all_risk_alerts(
        self,
        user_id: str,
        account_data: Dict,
        risk_settings: Dict,
        mt5_status: Optional[Dict] = None,
    ) -> Dict[str, bool]:
        """
        批量检查所有风险提醒

        Args:
            user_id: 用户ID
            account_data: 账户数据
            risk_settings: 风险控制设置
            mt5_status: MT5连接状态（可选）

        Returns:
            各项检查结果
        """
        results = {}

        # 1. MT5连接状态
        if mt5_status and mt5_status.get("failure_count", 0) > 0:
            results["mt5_lag"] = await self.check_mt5_lag(
                user_id=user_id,
                failure_count=mt5_status["failure_count"],
                last_response_time=mt5_status.get(
                    "last_response_time", "未知"
                ),
            )

        # 2. Binance净资产
        binance_asset = account_data.get("binance_net_asset", 0)
        binance_threshold = risk_settings.get("binance_net_asset_threshold")
        if binance_threshold is not None and binance_asset < binance_threshold:
            results["binance_net_asset"] = await self.check_binance_net_asset(
                user_id=user_id,
                current_asset=binance_asset,
                threshold=binance_threshold,
                is_below=True,
            )

        # 3. Bybit净资产
        bybit_asset = account_data.get("bybit_net_asset", 0)
        bybit_threshold = risk_settings.get("bybit_net_asset_threshold")
        if bybit_threshold is not None and bybit_asset < bybit_threshold:
            results["bybit_net_asset"] = await self.check_bybit_net_asset(
                user_id=user_id,
                current_asset=bybit_asset,
                threshold=bybit_threshold,
                is_below=True,
            )

        # 4. Binance爆仓价
        binance_liq = account_data.get("binance_liquidation_price")
        binance_price = account_data.get("binance_current_price")
        binance_liq_threshold_pct = risk_settings.get("binance_liquidation_distance_pct")

        if binance_liq and binance_price and binance_liq_threshold_pct is not None:
            distance = abs(binance_price - binance_liq)
            # Use user-configured distance percentage
            distance_threshold = binance_liq * (binance_liq_threshold_pct / 100.0)

            if distance < distance_threshold:
                # Critical if within half of threshold
                status = "⚠️ 接近安全线" if distance < distance_threshold * 0.5 else "注意价格变化"
                results["binance_liquidation"] = (
                    await self.check_binance_liquidation(
                        user_id=user_id,
                        current_price=binance_price,
                        liquidation_price=binance_liq,
                        distance=distance,
                        status=status,
                    )
                )

        # 5. Bybit爆仓价
        bybit_liq = account_data.get("bybit_liquidation_price")
        bybit_price = account_data.get("bybit_current_price")
        bybit_liq_threshold_pct = risk_settings.get("bybit_liquidation_distance_pct")

        if bybit_liq and bybit_price and bybit_liq_threshold_pct is not None:
            distance = abs(bybit_price - bybit_liq)
            # Use user-configured distance percentage
            distance_threshold = bybit_liq * (bybit_liq_threshold_pct / 100.0)

            if distance < distance_threshold:
                # Critical if within half of threshold
                status = "⚠️ 接近安全线" if distance < distance_threshold * 0.5 else "注意价格变化"
                results["bybit_liquidation"] = (
                    await self.check_bybit_liquidation(
                        user_id=user_id,
                        current_price=bybit_price,
                        liquidation_price=bybit_liq,
                        distance=distance,
                        status=status,
                    )
                )

        # 6. 资金费率 (空头)
        funding_threshold = risk_settings.get("funding_rate_threshold")
        if funding_threshold is not None:
            funding_data = await self._get_funding_rate()
            if funding_data:
                cost_per_lot = abs(funding_data.get('short_cost_per_lot', 0))
                if cost_per_lot > funding_threshold:
                    results["funding_rate"] = await self._send_alert(
                        user_id=user_id,
                        template_key="funding_rate_alert",
                        variables={
                            "pair_code": risk_settings.get("pair_code", "XAU"),
                            "funding_rate_pct": f"{funding_data['funding_rate_pct']:.4f}",
                            "short_cost": f"{funding_data['short_cost_per_lot']:.4f}",
                            "threshold": f"{funding_threshold}",
                            "mark_price": f"{funding_data['mark_price']:.2f}",
                        },
                    )

        # 7. 过夜费 (空头)
        overnight_threshold = risk_settings.get("overnight_fee_threshold")
        if overnight_threshold is not None:
            swap_data = await self._get_swap_rate()
            if swap_data:
                swap_short = abs(swap_data.get('short_swap_per_lot', 0))
                if swap_short > overnight_threshold:
                    results["overnight_fee"] = await self._send_alert(
                        user_id=user_id,
                        template_key="overnight_fee_alert",
                        variables={
                            "pair_code": risk_settings.get("pair_code", "XAU"),
                            "swap_short": f"{swap_data['short_swap_per_lot']:.4f}",
                            "threshold": f"{overnight_threshold}",
                            "symbol": swap_data.get("symbol", "XAUUSD+"),
                        },
                    )

        # 8. 单腿持仓（如果启用）
        if risk_settings.get("single_leg_alert_enabled", False):
            single_legs = account_data.get("single_leg_positions", [])
            for leg in single_legs:
                results[f"single_leg_{leg['exchange']}"] = (
                    await self.check_single_leg(
                        user_id=user_id,
                        exchange=leg["exchange"],
                        quantity=leg["quantity"],
                        duration=leg["duration"],
                        direction=leg["direction"],
                    )
                )

        return results

    # ========================================================================
    # 资金费率 + 过夜费 独立检查方法（供 broadcast_tasks 调用）
    # ========================================================================

    async def check_funding_rate(
        self,
        user_id: str,
        threshold_short: float = None,
        threshold_long: float = None,
        pair_code: str = "XAU",
    ) -> bool:
        funding_data = await self._get_funding_rate(pair_code)
        if not funding_data:
            return False
        sent = False
        # Short direction
        if threshold_short is not None:
            short_cost = abs(funding_data.get('short_cost_per_lot', 0))
            if short_cost > threshold_short:
                ok = await self._send_alert(
                    user_id=user_id,
                    template_key="funding_rate_alert",
                    variables={
                        "pair_code": pair_code,
                        "direction": "空",
                        "funding_rate_pct": f"{funding_data['funding_rate_pct']:.4f}",
                        "cost_per_lot": f"{short_cost:.4f}",
                        "short_cost": f"{short_cost:.4f}",
                        "threshold": f"{threshold_short}",
                        "mark_price": f"{funding_data['mark_price']:.2f}",
                    },
                )
                sent = sent or ok
        # Long direction
        if threshold_long is not None:
            long_cost = abs(funding_data.get('long_cost_per_lot', 0))
            if long_cost > threshold_long:
                ok = await self._send_alert(
                    user_id=user_id,
                    template_key="funding_rate_alert",
                    variables={
                        "pair_code": pair_code,
                        "direction": "多",
                        "funding_rate_pct": f"{funding_data['funding_rate_pct']:.4f}",
                        "cost_per_lot": f"{long_cost:.4f}",
                        "short_cost": f"{long_cost:.4f}",
                        "threshold": f"{threshold_long}",
                        "mark_price": f"{funding_data['mark_price']:.2f}",
                    },
                )
                sent = sent or ok
        return sent

    async def check_overnight_fee(
        self,
        user_id: str,
        threshold_short: float = None,
        threshold_long: float = None,
        pair_code: str = "XAU",
    ) -> bool:
        swap_data = await self._get_swap_rate(pair_code)
        if not swap_data:
            return False
        sent = False
        symbol = swap_data.get("symbol", "")
        # Short direction
        if threshold_short is not None:
            swap_short = abs(swap_data.get('short_swap_per_lot', 0))
            if swap_short > threshold_short:
                ok = await self._send_alert(
                    user_id=user_id,
                    template_key="overnight_fee_alert",
                    variables={
                        "pair_code": pair_code,
                        "direction": "空",
                        "swap_per_lot": f"{swap_data['short_swap_per_lot']:.4f}",
                        "swap_short": f"{swap_data['short_swap_per_lot']:.4f}",
                        "threshold": f"{threshold_short}",
                        "symbol": symbol,
                    },
                )
                sent = sent or ok
        # Long direction
        if threshold_long is not None:
            swap_long = abs(swap_data.get('long_swap_per_lot', 0))
            if swap_long > threshold_long:
                ok = await self._send_alert(
                    user_id=user_id,
                    template_key="overnight_fee_alert",
                    variables={
                        "pair_code": pair_code,
                        "direction": "多",
                        "swap_per_lot": f"{swap_data['long_swap_per_lot']:.4f}",
                        "swap_short": f"{swap_data['long_swap_per_lot']:.4f}",
                        "threshold": f"{threshold_long}",
                        "symbol": symbol,
                    },
                )
                sent = sent or ok
        return sent

    # ========================================================================
    # 费率数据获取（带缓存）
    # ========================================================================

    async def _get_funding_rate(self, pair_code: str = "XAU") -> Optional[Dict]:
        """Get funding rate for the pair's A-side symbol (Binance).

        Returns long_cost_per_lot and short_cost_per_lot:
        - funding_rate > 0: longs PAY shorts -> short benefits (cost negative), long pays (cost positive)
        - funding_rate < 0: shorts PAY longs -> long benefits, short pays
        """
        now = time.time()
        cache_entry = RiskAlertService._funding_cache.get(pair_code)
        if cache_entry and now - cache_entry.get('ts', 0) < 60:
            return cache_entry.get('data')

        try:
            from app.services.hedging_pair_service import hedging_pair_service
            pair = hedging_pair_service.get_pair(pair_code)
            if not pair:
                logger.warning(f"[RiskAlert] Unknown pair_code: {pair_code}")
                return cache_entry.get('data') if cache_entry else None

            symbol_a = pair.symbol_a.symbol  # e.g. XAUUSDT
            conversion_factor = pair.conversion_factor or 100.0

            from app.services.binance_client import BinanceFuturesClient
            client = BinanceFuturesClient("", "")
            try:
                data = await client.get_premium_index(symbol_a)
            finally:
                await client.close()

            funding_rate = float(data.get("lastFundingRate", 0))
            mark_price = float(data.get("markPrice", 0))
            per_lot = funding_rate * mark_price * conversion_factor
            # Convention: cost > 0 means user pays funding
            # long pays when funding_rate > 0
            # short pays when funding_rate < 0
            result = {
                "pair_code": pair_code,
                "symbol": symbol_a,
                "funding_rate": funding_rate,
                "funding_rate_pct": round(funding_rate * 100, 6),
                "mark_price": mark_price,
                "long_cost_per_lot": round(per_lot, 4),       # positive when rate > 0
                "short_cost_per_lot": round(-per_lot, 4),     # positive when rate < 0
            }
            RiskAlertService._funding_cache[pair_code] = {'data': result, 'ts': now}
            return result
        except Exception as e:
            logger.warning(f"[RiskAlert] Failed to fetch funding rate for {pair_code}: {e}")
            return cache_entry.get('data') if cache_entry else None

    async def _get_swap_rate(self, pair_code: str = "XAU") -> Optional[Dict]:
        """Get swap (overnight) rate via MT5 Bridge HTTP (Linux-compatible).

        Computes per-lot per-day swap cost in USD using MT5 symbol_info.
        """
        now = time.time()
        cache_entry = RiskAlertService._swap_cache.get(pair_code)
        if cache_entry and now - cache_entry.get('ts', 0) < 60:
            return cache_entry.get('data')

        try:
            from app.services.hedging_pair_service import hedging_pair_service
            pair = hedging_pair_service.get_pair(pair_code)
            if not pair:
                return cache_entry.get('data') if cache_entry else None

            mt5_symbol = pair.symbol_b.symbol
            mt5_platform_id = pair.symbol_b.platform_id

            # Resolve bridge URL from system MT5 client (per-platform)
            from app.core.database import AsyncSessionLocal
            from app.models.mt5_client import MT5Client as MT5ClientModel
            from app.models.account import Account
            from sqlalchemy import select as _sa_sel
            import os
            import httpx

            bridge_url = None
            async with AsyncSessionLocal() as _db:
                row = (await _db.execute(
                    _sa_sel(MT5ClientModel, Account.platform_id)
                    .join(Account, MT5ClientModel.account_id == Account.account_id)
                    .where(MT5ClientModel.is_active == True)
                    .where(MT5ClientModel.is_system_service == True)
                    .where(Account.platform_id == mt5_platform_id)
                    .limit(1)
                )).first()
                if row:
                    mc, _ = row
                    bridge_url = mc.bridge_url or f"http://172.31.14.113:{mc.bridge_service_port}"

            if not bridge_url:
                logger.warning(f"[RiskAlert] No MT5 bridge for pair {pair_code} platform_id={mt5_platform_id}")
                return cache_entry.get('data') if cache_entry else None

            api_key = os.getenv("MT5_API_KEY", "")
            headers = {"X-Api-Key": api_key} if api_key else {}

            async with httpx.AsyncClient(timeout=3.0) as _http:
                resp = await _http.get(
                    f"{bridge_url}/mt5/symbol_info/{mt5_symbol}",
                    headers=headers,
                )
                if resp.status_code != 200:
                    return cache_entry.get('data') if cache_entry else None
                info = resp.json()

            swap_long = float(info.get("swap_long", 0) or 0)
            swap_short = float(info.get("swap_short", 0) or 0)
            contract = float(info.get("trade_contract_size", 100) or 100)

            result = {
                "pair_code": pair_code,
                "symbol": mt5_symbol,
                "swap_long": swap_long,
                "swap_short": swap_short,
                "long_swap_per_lot": round(swap_long * contract / 365, 4) if swap_long else 0,
                "short_swap_per_lot": round(swap_short * contract / 365, 4) if swap_short else 0,
            }
            RiskAlertService._swap_cache[pair_code] = {'data': result, 'ts': now}
            return result
        except Exception as e:
            logger.warning(f"[RiskAlert] Failed to fetch swap rate for {pair_code}: {e}")
            return cache_entry.get('data') if cache_entry else None

    # ========================================================================
    # 爆仓价计算辅助函数
    # ========================================================================

    def _calculate_binance_liquidation_price(
        self,
        entry_price: float,
        leverage: float,
        position_side: str = "LONG"
    ) -> float:
        """
        计算 Binance 爆仓价

        Args:
            entry_price: 开仓均价
            leverage: 杠杆倍数
            position_side: 持仓方向 (LONG/SHORT)

        Returns:
            爆仓价
        """
        if entry_price == 0 or leverage == 0:
            return 0

        if position_side == "LONG":
            # 多仓强平价 = 开仓价 × (1 − 1/杠杆)
            return entry_price * (1 - 1 / leverage)
        else:
            # 空仓强平价 = 开仓价 × (1 + 1/杠杆)
            return entry_price * (1 + 1 / leverage)

    def _calculate_bybit_mt5_liquidation_price(
        self,
        entry_price: float,
        equity: float,
        volume_oz: float,
        position_side: str = "LONG"
    ) -> float:
        """
        计算 Bybit MT5 爆仓价

        Args:
            entry_price: 开仓均价
            equity: 账户净值
            volume_oz: 持仓盎司数
            position_side: 持仓方向 (LONG/SHORT)

        Returns:
            爆仓价
        """
        if entry_price == 0 or volume_oz == 0:
            return 0

        price_offset = equity / volume_oz

        if position_side == "LONG":
            # 多头强平价 = 开仓价 − (账户净值 ÷ 持仓盎司数)
            liquidation_price = entry_price - price_offset
            return liquidation_price if liquidation_price > 0 else 0
        else:
            # 空头强平价 = 开仓价 + (账户净值 ÷ 持仓盎司数)
            return entry_price + price_offset
