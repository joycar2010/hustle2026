"""Spread alert notification service"""
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.config import settings
from app.services.feishu_service import get_feishu_service
from app.models.notification_config import NotificationTemplate, NotificationLog
from app.websocket.manager import manager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import uuid

logger = logging.getLogger(__name__)


def get_beijing_time():
    """Get current time in Beijing timezone (UTC+8) as naive datetime"""
    beijing_tz = ZoneInfo("Asia/Shanghai")
    beijing_time = datetime.now(beijing_tz)
    return beijing_time.replace(tzinfo=None)


class SpreadAlertService:
    """
    点差值提醒服务

    集成到风险控制系统，当点差值达到阈值时发送通知
    """

    def __init__(self):
        self.last_alert_time = {}  # 记录上次提醒时间，避免频繁通知
        self.condition_counters = {}  # 记录连续满足条件的次数 {user_id: {alert_type: count}}

    async def check_and_send_spread_alerts(
        self,
        db: AsyncSession,
        user_id: str,
        market_data: Dict[str, Any],
        alert_settings: Dict[str, Any]
    ):
        """
        检查点差值并发送提醒（支持同步次数确认）

        Args:
            db: 数据库会话
            user_id: 用户ID
            market_data: 市场数据 {forward_spread, reverse_spread}
            alert_settings: 提醒设置 {
                forwardOpenPrice, forwardClosePrice, reverseOpenPrice, reverseClosePrice,
                forwardOpenSyncCount, forwardCloseSyncCount, reverseOpenSyncCount, reverseCloseSyncCount
            }

        触发规则：
        - 正向开仓: 点差 >= forwardOpenPrice 且连续满足 forwardOpenSyncCount 次
        - 正向平仓: 点差 <= forwardClosePrice 且连续满足 forwardCloseSyncCount 次
        - 反向开仓: 点差 >= reverseOpenPrice 且连续满足 reverseOpenSyncCount 次
        - 反向平仓: 点差 <= reverseClosePrice 且连续满足 reverseCloseSyncCount 次
        - 空值: 不触发任何提醒
        """
        alerts_to_send = []

        # 初始化用户的计数器
        if user_id not in self.condition_counters:
            self.condition_counters[user_id] = {}

        # 1. 检查正向开仓点差值（点差 >= 阈值）
        if market_data.get('forward_spread') is not None and alert_settings.get('forwardOpenPrice') is not None:
            spread = market_data['forward_spread']
            threshold = alert_settings['forwardOpenPrice']
            sync_count = alert_settings.get('forwardOpenSyncCount', 1)  # 默认1次

            alert_type = 'forward_open'
            if spread >= threshold:
                # 条件满足，增加计数
                self.condition_counters[user_id][alert_type] = self.condition_counters[user_id].get(alert_type, 0) + 1

                # 检查是否达到同步次数
                if self.condition_counters[user_id][alert_type] >= sync_count:
                    alerts_to_send.append({
                        'template_key': 'forward_open_spread_alert',
                        'variables': {
                            'spread': f"{spread:.2f}",
                            'threshold': f"{threshold:.2f}"
                        }
                    })
                    # 重置计数器
                    self.condition_counters[user_id][alert_type] = 0
            else:
                # 条件不满足，重置计数
                self.condition_counters[user_id][alert_type] = 0

        # 2. 检查正向平仓点差值（点差 <= 阈值）
        if market_data.get('forward_spread') is not None and alert_settings.get('forwardClosePrice') is not None:
            spread = market_data['forward_spread']
            threshold = alert_settings['forwardClosePrice']
            sync_count = alert_settings.get('forwardCloseSyncCount', 1)  # 默认1次

            alert_type = 'forward_close'
            if spread <= threshold:
                # 条件满足，增加计数
                self.condition_counters[user_id][alert_type] = self.condition_counters[user_id].get(alert_type, 0) + 1

                # 检查是否达到同步次数
                if self.condition_counters[user_id][alert_type] >= sync_count:
                    alerts_to_send.append({
                        'template_key': 'forward_close_spread_alert',
                        'variables': {
                            'spread': f"{spread:.2f}",
                            'threshold': f"{threshold:.2f}"
                        }
                    })
                    # 重置计数器
                    self.condition_counters[user_id][alert_type] = 0
            else:
                # 条件不满足，重置计数
                self.condition_counters[user_id][alert_type] = 0

        # 3. 检查反向开仓点差值（点差 >= 阈值）
        if market_data.get('reverse_spread') is not None and alert_settings.get('reverseOpenPrice') is not None:
            spread = market_data['reverse_spread']
            threshold = alert_settings['reverseOpenPrice']
            sync_count = alert_settings.get('reverseOpenSyncCount', 1)  # 默认1次

            alert_type = 'reverse_open'
            if spread >= threshold:
                # 条件满足，增加计数
                self.condition_counters[user_id][alert_type] = self.condition_counters[user_id].get(alert_type, 0) + 1

                # 检查是否达到同步次数
                if self.condition_counters[user_id][alert_type] >= sync_count:
                    alerts_to_send.append({
                        'template_key': 'reverse_open_spread_alert',
                        'variables': {
                            'spread': f"{spread:.2f}",
                            'threshold': f"{threshold:.2f}"
                        }
                    })
                    # 重置计数器
                    self.condition_counters[user_id][alert_type] = 0
            else:
                # 条件不满足，重置计数
                self.condition_counters[user_id][alert_type] = 0

        # 4. 检查反向平仓点差值（点差 <= 阈值）
        if market_data.get('reverse_spread') is not None and alert_settings.get('reverseClosePrice') is not None:
            spread = market_data['reverse_spread']
            threshold = alert_settings['reverseClosePrice']
            sync_count = alert_settings.get('reverseCloseSyncCount', 1)  # 默认1次

            alert_type = 'reverse_close'
            if spread <= threshold:
                # 条件满足，增加计数
                self.condition_counters[user_id][alert_type] = self.condition_counters[user_id].get(alert_type, 0) + 1

                # 检查是否达到同步次数
                if self.condition_counters[user_id][alert_type] >= sync_count:
                    alerts_to_send.append({
                        'template_key': 'reverse_close_spread_alert',
                        'variables': {
                            'spread': f"{spread:.2f}",
                            'threshold': f"{threshold:.2f}"
                        }
                    })
                    # 重置计数器
                    self.condition_counters[user_id][alert_type] = 0
            else:
                # 条件不满足，重置计数
                self.condition_counters[user_id][alert_type] = 0

        # 发送所有提醒（冷却时间检查在_send_alert中进行）
        for alert in alerts_to_send:
            await self._send_alert(db, user_id, alert['template_key'], alert['variables'])

    def _should_send_alert(self, alert_type: str, user_id: str) -> bool:
        """
        检查是否应该发送提醒（冷却时间控制）

        Args:
            alert_type: 提醒类型
            user_id: 用户ID

        Returns:
            是否应该发送
        """
        key = f"{alert_type}_{user_id}"
        now = get_beijing_time()

        if key in self.last_alert_time:
            last_time = self.last_alert_time[key]
            # 冷却时间5秒
            if (now - last_time).total_seconds() < settings.SPREAD_ALERT_COOLDOWN:
                return False

        self.last_alert_time[key] = now
        return True

    async def _send_alert(
        self,
        db: AsyncSession,
        user_id: str,
        template_key: str,
        variables: Dict[str, str]
    ):
        """
        发送提醒通知

        Args:
            db: 数据库会话
            user_id: 用户ID
            template_key: 模板key
            variables: 模板变量
        """
        try:
            # 获取实时账户数据（暂时禁用，函数不存在）
            # from app.services.account_service import get_account_summary
            # try:
            #     account_data = await get_account_summary(db, uuid.UUID(user_id))
            #     # 添加实时账户信息到变量中
            #     variables.update({
            #         'binance_balance': f"{account_data.get('binance_net_asset', 0):.2f}",
            #         'bybit_balance': f"{account_data.get('bybit_mt5_net_asset', 0):.2f}",
            #         'total_assets': f"{account_data.get('total_assets', 0):.2f}"
            #     })
            # except Exception as e:
            #     logger.warning(f"获取账户数据失败: {e}")
            # 使用默认值（防止模板因缺失变量而格式化失败）
            variables.setdefault('binance_balance', '0.00')
            variables.setdefault('bybit_balance', '0.00')
            variables.setdefault('total_assets', '0.00')
            # 模板变量补全：当前模板使用 estimated_profit / current_profit
            # （没有真实的盈利预估器，使用 N/A 占位避免 KeyError）
            variables.setdefault('estimated_profit', 'N/A')
            variables.setdefault('current_profit', 'N/A')

            # 获取模板
            result = await db.execute(
                select(NotificationTemplate).filter(
                    and_(
                        NotificationTemplate.template_key == template_key,
                        NotificationTemplate.is_active == True,
                        NotificationTemplate.enable_feishu == True,
                        NotificationTemplate.auto_check_enabled == True  # 检查是否启用自动检查
                    )
                )
            )
            template = result.scalar_one_or_none()

            if not template:
                logger.warning(f"模板不存在、未启用或未开启自动检查: {template_key}")
                return

            # 检查冷却时间（使用模板的配置）
            cooldown = template.cooldown_seconds or 0
            if cooldown > 0:
                key = f"{template_key}_{user_id}"
                now = get_beijing_time()

                if key in self.last_alert_time:
                    last_time = self.last_alert_time[key]
                    elapsed = (now - last_time).total_seconds()
                    if elapsed < cooldown:
                        logger.info(f"模板 {template_key} 在冷却中，剩余 {cooldown - elapsed:.0f} 秒")
                        return

                self.last_alert_time[key] = now

            # 渲染模板（safe format：缺失变量回退为占位符而不是抛 KeyError）
            class _SafeDict(dict):
                def __missing__(self, key):
                    return '{' + key + '}'
            _vars = _SafeDict(variables)
            title = template.title_template.format_map(_vars)
            content = template.content_template.format_map(_vars)

            # 发送飞书通知
            feishu = get_feishu_service()
            if not feishu:
                logger.warning("飞书服务未初始化")
                return

            # 获取用户信息（这里简化处理，实际应该从user_notification_settings获取）
            from app.models.user import User
            import uuid as uuid_lib
            user_result = await db.execute(
                select(User).filter(User.user_id == uuid_lib.UUID(user_id))
            )
            user = user_result.scalar_one_or_none()

            if not user:
                logger.warning(f"用户不存在: {user_id}")
                return

            # 使用飞书open_id作为接收者ID，如果没有则使用邮箱
            if user.feishu_open_id:
                recipient = user.feishu_open_id
                receive_id_type = "open_id"
            else:
                recipient = user.email
                receive_id_type = "email"
                logger.warning(f"用户 {user_id} 没有配置飞书open_id，使用邮箱: {recipient}")

            # 根据优先级设置颜色
            color_map = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
            color = color_map.get(template.priority, "orange")

            # 发送卡片消息
            result = await feishu.send_card_message(
                receive_id=recipient,
                title=title,
                content=content,
                receive_id_type=receive_id_type,
                color=color
            )

            # ─── WebSocket popup via Go Redis Bridge ──────────────────────────────
            # Python ws_manager.active_connections is EMPTY because the frontend
            # connects to Go /ws, not Python /api/v1/ws.
            # Correct path: Python → Redis ws:user_event → Go Redis Bridge → Go Hub → Client.
            try:
                from app.core.redis_client import redis_client as _rc

                alert_type_map = {
                    "forward_open_spread_alert":  "forward_open",
                    "forward_close_spread_alert": "forward_close",
                    "reverse_open_spread_alert":  "reverse_open",
                    "reverse_close_spread_alert": "reverse_close",
                }
                level_map = {1: "info", 2: "info", 3: "warning", 4: "critical"}

                popup_title = (
                    template.popup_title_template.format_map(_vars)
                    if template.popup_title_template
                    else title
                )
                popup_content = (
                    template.popup_content_template.format_map(_vars)
                    if template.popup_content_template
                    else content
                )

                # Payload shape expected by Go redis_bridge ws:user_event handler:
                # { user_id, type, data }
                evt_payload = {
                    "user_id": user_id,
                    "type": "risk_alert",
                    "data": {
                        "alert_type":   alert_type_map.get(template_key, template_key),
                        "level":        level_map.get(template.priority, "warning"),
                        "title":        title,
                        "message":      content,
                        "timestamp":    get_beijing_time().isoformat(),
                        "template_key": template_key,
                        "popup_config": {
                            "title":        popup_title,
                            "content":      popup_content,
                            "sound_file":   template.alert_sound_file or "/sounds/hello-moto.mp3",
                            "sound_repeat": template.alert_sound_repeat or 3,
                        },
                    },
                }
                import json as _json
                await _rc.publish("ws:user_event", _json.dumps(evt_payload))
                logger.info(f"[SPREAD_ALERT] WS popup via Redis bridge: {template_key} for {user_id}")
            except Exception as ws_err:
                logger.warning(f"[SPREAD_ALERT] Redis WS publish failed: {ws_err}")

            # 音频提醒功能已禁用 - 只发送文字卡片消息

            # 记录日志
            log = NotificationLog(
                user_id=uuid_lib.UUID(user_id),
                template_key=template_key,
                service_type="feishu",
                recipient=recipient,
                title=title,
                content=content,
                status="sent" if result.get("success") else "failed",
                error_message=result.get("error"),
                sent_at=get_beijing_time() if result.get("success") else None
            )
            db.add(log)
            await db.commit()

            if result.get("success"):
                logger.info(f"点差值提醒发送成功: {template_key} -> {user_id}")
            else:
                logger.error(f"点差值提醒发送失败: {template_key} -> {user_id}, 错误: {result.get('error')}")
            # NOTE: WebSocket popup broadcast happens earlier (right after Feishu send),
            # using the new block with full popup_config — see the [SPREAD_ALERT] log line.
            # Legacy _broadcast_alert_to_frontend was missing popup_config and is now bypassed.

        except Exception as e:
            logger.error(f"发送点差值提醒失败: {e}", exc_info=True)

    async def _broadcast_alert_to_frontend(
        self,
        user_id: str,
        template_key: str,
        template: NotificationTemplate,
        variables: Dict[str, str]
    ):
        """通过WebSocket广播提醒到前端"""
        try:
            # 映射模板Key到前端Alert Type
            alert_type_map = {
                'forward_open_spread_alert': 'forward_open',
                'forward_close_spread_alert': 'forward_close',
                'reverse_open_spread_alert': 'reverse_open',
                'reverse_close_spread_alert': 'reverse_close'
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
                    "template_key": template_key
                }
            }

            # 广播到指定用户
            await manager.send_to_user(
                message=alert_message,
                user_id=user_id
            )

            logger.info(f"Alert broadcasted to frontend: {template_key} for user {user_id}")

        except Exception as e:
            logger.error(f"Error broadcasting alert to frontend: {e}")


# 全局实例
spread_alert_service = SpreadAlertService()
