"""Spread alert notification service"""
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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

    async def check_and_send_spread_alerts(
        self,
        db: AsyncSession,
        user_id: str,
        market_data: Dict[str, Any],
        alert_settings: Dict[str, Any]
    ):
        """
        检查点差值并发送提醒

        Args:
            db: 数据库会话
            user_id: 用户ID
            market_data: 市场数据 {forward_spread, reverse_spread}
            alert_settings: 提醒设置 {forwardOpenPrice, forwardClosePrice, reverseOpenPrice, reverseClosePrice}
        """
        alerts_to_send = []

        # 1. 检查正向开仓点差值
        if market_data.get('forward_spread') and alert_settings.get('forwardOpenPrice'):
            if abs(market_data['forward_spread']) >= alert_settings['forwardOpenPrice']:
                if self._should_send_alert('forward_open', user_id):
                    alerts_to_send.append({
                        'template_key': 'forward_open_spread_alert',
                        'variables': {
                            'spread': f"{market_data['forward_spread']:.2f}",
                            'threshold': f"{alert_settings['forwardOpenPrice']:.2f}",
                            'market_status': '优惠价格出现',
                            'estimated_profit': f"{abs(market_data['forward_spread']) * 10:.2f}"  # 假设10件
                        }
                    })

        # 2. 检查正向平仓点差值
        if market_data.get('forward_spread') and alert_settings.get('forwardClosePrice'):
            if abs(market_data['forward_spread']) <= alert_settings['forwardClosePrice']:
                if self._should_send_alert('forward_close', user_id):
                    alerts_to_send.append({
                        'template_key': 'forward_close_spread_alert',
                        'variables': {
                            'spread': f"{market_data['forward_spread']:.2f}",
                            'threshold': f"{alert_settings['forwardClosePrice']:.2f}",
                            'market_status': '价格回归正常',
                            'current_profit': f"{abs(market_data['forward_spread']) * 10:.2f}"
                        }
                    })

        # 3. 检查反向开仓点差值
        if market_data.get('reverse_spread') and alert_settings.get('reverseOpenPrice'):
            if abs(market_data['reverse_spread']) >= alert_settings['reverseOpenPrice']:
                if self._should_send_alert('reverse_open', user_id):
                    alerts_to_send.append({
                        'template_key': 'reverse_open_spread_alert',
                        'variables': {
                            'spread': f"{market_data['reverse_spread']:.2f}",
                            'threshold': f"{alert_settings['reverseOpenPrice']:.2f}",
                            'market_status': '反向优惠出现',
                            'estimated_profit': f"{abs(market_data['reverse_spread']) * 10:.2f}"
                        }
                    })

        # 4. 检查反向平仓点差值
        if market_data.get('reverse_spread') and alert_settings.get('reverseClosePrice'):
            if abs(market_data['reverse_spread']) <= alert_settings['reverseClosePrice']:
                if self._should_send_alert('reverse_close', user_id):
                    alerts_to_send.append({
                        'template_key': 'reverse_close_spread_alert',
                        'variables': {
                            'spread': f"{market_data['reverse_spread']:.2f}",
                            'threshold': f"{alert_settings['reverseClosePrice']:.2f}",
                            'market_status': '反向价格回归',
                            'current_profit': f"{abs(market_data['reverse_spread']) * 10:.2f}"
                        }
                    })

        # 发送所有提醒
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
            # 冷却时间60秒
            if (now - last_time).total_seconds() < 60:
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
            # 获取模板
            result = await db.execute(
                select(NotificationTemplate).filter(
                    and_(
                        NotificationTemplate.template_key == template_key,
                        NotificationTemplate.is_active == True,
                        NotificationTemplate.enable_feishu == True
                    )
                )
            )
            template = result.scalar_one_or_none()

            if not template:
                logger.warning(f"模板不存在或未启用: {template_key}")
                return

            # 渲染模板
            title = template.title_template.format(**variables)
            content = template.content_template.format(**variables)

            # 发送飞书通知
            feishu = get_feishu_service()
            if not feishu:
                logger.warning("飞书服务未初始化")
                return

            # 获取用户信息（这里简化处理，实际应该从user_notification_settings获取）
            from app.models.user import User
            user_result = await db.execute(
                select(User).filter(User.user_id == uuid.UUID(user_id))
            )
            user = user_result.scalar_one_or_none()

            if not user:
                logger.warning(f"用户不存在: {user_id}")
                return

            # 使用邮箱作为接收者ID
            recipient = user.email

            # 根据优先级设置颜色
            color_map = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
            color = color_map.get(template.priority, "orange")

            # 发送卡片消息
            result = await feishu.send_card_message(
                receive_id=recipient,
                title=title,
                content=content,
                receive_id_type="email",
                color=color
            )

            # 如果模板配置了声音提醒，发送音频消息
            if result.get("success") and template.alert_sound:
                try:
                    import os
                    # 构造音频文件路径（假设音频文件存储在 frontend/public/sounds/ 目录）
                    audio_path = os.path.join("frontend", "public", "sounds", template.alert_sound)

                    if os.path.exists(audio_path):
                        # 上传音频文件
                        upload_result = await feishu.upload_audio_file(audio_path)

                        if upload_result.get("success"):
                            file_key = upload_result.get("file_key")
                            # 发送音频消息
                            audio_result = await feishu.send_audio_message(
                                receive_id=recipient,
                                file_key=file_key,
                                receive_id_type="email"
                            )

                            if audio_result.get("success"):
                                logger.info(f"音频提醒发送成功: {template.alert_sound}")
                            else:
                                logger.warning(f"音频提醒发送失败: {audio_result.get('error')}")
                        else:
                            logger.warning(f"音频文件上传失败: {upload_result.get('error')}")
                    else:
                        logger.warning(f"音频文件不存在: {audio_path}")
                except Exception as e:
                    logger.error(f"发送音频提醒失败: {e}", exc_info=True)

            # 记录日志
            log = NotificationLog(
                user_id=uuid.UUID(user_id),
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

                # 通过WebSocket推送到前端
                await self._broadcast_alert_to_frontend(
                    user_id=user_id,
                    template_key=template_key,
                    template=template,
                    variables=variables
                )
            else:
                logger.error(f"点差值提醒发送失败: {template_key} -> {user_id}, 错误: {result.get('error')}")

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
            await manager.send_personal_message(
                message=alert_message,
                user_id=user_id
            )

            logger.info(f"Alert broadcasted to frontend: {template_key} for user {user_id}")

        except Exception as e:
            logger.error(f"Error broadcasting alert to frontend: {e}")


# 全局实例
spread_alert_service = SpreadAlertService()
