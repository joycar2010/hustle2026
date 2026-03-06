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
from app.models.notification_config import NotificationConfig
from app.websocket.connection_manager import manager

logger = logging.getLogger(__name__)


def get_beijing_time():
    """Get current time in Beijing timezone (UTC+8) as naive datetime"""
    beijing_tz = ZoneInfo("Asia/Shanghai")
    beijing_time = datetime.now(beijing_tz)
    return beijing_time.replace(tzinfo=None)


class RiskAlertService:
    """风险控制提醒服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        # 冷却时间缓存：{user_id}_{template_key} -> last_sent_time
        self.cooldown_cache: Dict[str, datetime] = {}

    async def _can_send_alert(
        self, user_id: str, template_key: str, cooldown_seconds: int = 60
    ) -> bool:
        """检查是否可以发送提醒（冷却时间）"""
        cache_key = f"{user_id}_{template_key}"
        last_sent = self.cooldown_cache.get(cache_key)

        if last_sent:
            elapsed = (get_beijing_time() - last_sent).total_seconds()
            if elapsed < cooldown_seconds:
                return False

        return True

    async def _send_alert(
        self,
        user_id: str,
        template_key: str,
        variables: Dict[str, any],
    ) -> bool:
        """发送提醒通知"""
        try:
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

            # 检查冷却时间
            if not await self._can_send_alert(
                user_id, template_key, template.cooldown_seconds
            ):
                logger.debug(
                    f"Alert {template_key} for user {user_id} is in cooldown"
                )
                return False

            # 获取飞书配置
            result = await self.db.execute(
                select(NotificationConfig).where(
                    NotificationConfig.user_id == user_id,
                    NotificationConfig.service_type == "feishu",
                )
            )
            config = result.scalar_one_or_none()

            if not config or not config.enabled:
                logger.debug(f"Feishu not enabled for user {user_id}")
                return False

            # 格式化消息
            title = template.title_template.format(**variables)
            content = template.content_template.format(**variables)

            # 获取飞书服务
            feishu = get_feishu_service()
            if not feishu:
                logger.warning("飞书服务未初始化")
                return False

            # 根据优先级设置颜色
            color_map = {1: "blue", 2: "blue", 3: "orange", 4: "red"}
            color = color_map.get(template.priority, "orange")

            # 发送飞书卡片消息
            result = await feishu.send_card_message(
                receive_id=config.receiver_id,
                title=title,
                content=content,
                receive_id_type="email",
                color=color
            )

            success = result.get("success", False)

            # 如果卡片消息发送成功且模板配置了声音提醒，发送音频消息
            if success and template.alert_sound:
                try:
                    import os
                    # 构造音频文件路径
                    audio_path = os.path.join("frontend", "public", "sounds", template.alert_sound)

                    if os.path.exists(audio_path):
                        # 上传音频文件
                        upload_result = await feishu.upload_audio_file(audio_path)

                        if upload_result.get("success"):
                            file_key = upload_result.get("file_key")
                            # 发送音频消息
                            audio_result = await feishu.send_audio_message(
                                receive_id=config.receiver_id,
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

            if success:
                # 更新冷却时间
                cache_key = f"{user_id}_{template_key}"
                self.cooldown_cache[cache_key] = get_beijing_time()
                logger.info(f"Alert sent: {template_key} to user {user_id}")

                # 通过WebSocket推送到前端
                await self._broadcast_alert_to_frontend(
                    user_id=user_id,
                    template_key=template_key,
                    template=template,
                    variables=variables
                )

            return success

        except Exception as e:
            logger.error(f"Error sending alert {template_key}: {e}")
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
                'binance_liquidation_alert': 'binance_liquidation',
                'bybit_liquidation_alert': 'bybit_liquidation',
                'single_leg_alert': 'single_leg_alert'
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
        if failure_count > 0:
            return await self._send_alert(
                user_id=user_id,
                template_key="mt5_lag_alert",
                variables={
                    "failure_count": failure_count,
                    "last_response_time": last_response_time,
                },
            )
        return False

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
    ) -> bool:
        """
        检查单腿持仓

        Args:
            user_id: 用户ID
            exchange: 交易所名称（如"Binance"或"Bybit"）
            quantity: 单腿数量
            duration: 持续时间（秒）
            direction: 方向（"多头"或"空头"）

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
            },
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
        if binance_threshold and binance_asset < binance_threshold:
            results["binance_net_asset"] = await self.check_binance_net_asset(
                user_id=user_id,
                current_asset=binance_asset,
                threshold=binance_threshold,
                is_below=True,
            )

        # 3. Bybit净资产
        bybit_asset = account_data.get("bybit_net_asset", 0)
        bybit_threshold = risk_settings.get("bybit_net_asset_threshold")
        if bybit_threshold and bybit_asset < bybit_threshold:
            results["bybit_net_asset"] = await self.check_bybit_net_asset(
                user_id=user_id,
                current_asset=bybit_asset,
                threshold=bybit_threshold,
                is_below=True,
            )

        # 4. Binance爆仓价
        binance_liq = account_data.get("binance_liquidation_price")
        binance_price = account_data.get("binance_current_price")
        if binance_liq and binance_price:
            distance = abs(binance_price - binance_liq)
            if distance < binance_liq * 0.1:  # 距离小于10%
                status = "⚠️ 接近安全线" if distance < binance_liq * 0.05 else "注意价格变化"
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
        if bybit_liq and bybit_price:
            distance = abs(bybit_price - bybit_liq)
            if distance < bybit_liq * 0.1:  # 距离小于10%
                status = "⚠️ 接近安全线" if distance < bybit_liq * 0.05 else "注意价格变化"
                results["bybit_liquidation"] = (
                    await self.check_bybit_liquidation(
                        user_id=user_id,
                        current_price=bybit_price,
                        liquidation_price=bybit_liq,
                        distance=distance,
                        status=status,
                    )
                )

        # 6. 单腿持仓（如果启用）
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
