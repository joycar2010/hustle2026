"""Risk monitoring service for detecting and preventing risky trading conditions"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from uuid import UUID
import redis.asyncio as redis
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.account import Account
from app.models.strategy import StrategyConfig
from app.models.risk_alert import RiskAlert
from app.services.account_service import account_data_service
from app.services.market_service import market_data_service
from app.websocket.manager import manager


class RiskMonitor:
    """Service for monitoring and managing trading risks"""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.emergency_stop_active = False

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection"""
        if self.redis_client is None:
            self.redis_client = await redis.from_url(settings.REDIS_URL)
        return self.redis_client

    async def check_mt5_stuck(
        self,
        symbol: str = "XAUUSDT",
        threshold: int = 5,
    ) -> Dict[str, Any]:
        """Check if MT5 data is stuck (not updating)

        Args:
            symbol: Symbol to check
            threshold: Number of consecutive unchanged prices to trigger alert

        Returns:
            Dict with stuck status and counter
        """
        redis_client = await self._get_redis()
        key = f"mt5_stuck_counter:{symbol}"

        # Get current market data
        try:
            spread_data = await market_data_service.get_current_spread(use_cache=False)
            current_price = spread_data.bybit_quote.bid_price
            current_time = spread_data.timestamp

            # Get last recorded data
            last_data = await redis_client.get(key)

            if last_data:
                last_record = json.loads(last_data)
                last_price = last_record["price"]
                last_time = last_record["timestamp"]
                counter = last_record["counter"]

                # Check if price hasn't changed and time has passed
                time_diff = (current_time - last_time) / 1000  # Convert to seconds

                if last_price == current_price and time_diff > 1:
                    counter += 1
                else:
                    counter = 0

                # Store updated data
                await redis_client.set(
                    key,
                    json.dumps({
                        "price": current_price,
                        "timestamp": current_time,
                        "counter": counter,
                    }),
                    ex=300,  # Expire after 5 minutes
                )

                is_stuck = counter >= threshold

                return {
                    "is_stuck": is_stuck,
                    "counter": counter,
                    "threshold": threshold,
                    "last_price": last_price,
                    "current_price": current_price,
                    "time_diff": time_diff,
                }
            else:
                # First check, initialize
                await redis_client.set(
                    key,
                    json.dumps({
                        "price": current_price,
                        "timestamp": current_time,
                        "counter": 0,
                    }),
                    ex=300,
                )

                return {
                    "is_stuck": False,
                    "counter": 0,
                    "threshold": threshold,
                }

        except Exception as e:
            return {
                "error": str(e),
                "is_stuck": False,
            }

    async def check_account_risk(
        self,
        account: Account,
        max_risk_ratio: float = 80.0,
    ) -> Dict[str, Any]:
        """Check if account risk ratio exceeds threshold

        Args:
            account: Account to check
            max_risk_ratio: Maximum acceptable risk ratio (%)

        Returns:
            Dict with risk status
        """
        try:
            # Get account balance
            if account.platform_id == 1:  # Binance
                balance = await account_data_service.get_binance_balance(
                    account.api_key,
                    account.api_secret,
                )
            elif account.platform_id == 2:  # Bybit
                # Bybit V5 API only supports UNIFIED account type
                balance = await account_data_service.get_bybit_balance(
                    account.api_key,
                    account.api_secret,
                    "UNIFIED",
                    mt5_id=account.mt5_id if account.is_mt5_account else None,
                    mt5_password=account.mt5_primary_pwd if account.is_mt5_account else None,
                    mt5_server=account.mt5_server if account.is_mt5_account else None,
                )
            else:
                return {"error": "Unknown platform"}

            risk_ratio = balance.risk_ratio or 0
            is_high_risk = risk_ratio >= max_risk_ratio

            return {
                "is_high_risk": is_high_risk,
                "risk_ratio": risk_ratio,
                "max_risk_ratio": max_risk_ratio,
                "account_id": str(account.account_id),
                "account_name": account.account_name,
            }

        except Exception as e:
            return {
                "error": str(e),
                "is_high_risk": False,
            }

    async def check_position_limits(
        self,
        account: Account,
        quantity: float,
        max_position_size: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Check if new position would exceed limits

        Args:
            account: Account to check
            quantity: Proposed order quantity
            max_position_size: Maximum allowed position size

        Returns:
            Dict with limit check result
        """
        try:
            # Get current positions
            if account.platform_id == 1:  # Binance
                positions = await account_data_service.get_binance_positions(
                    account.api_key,
                    account.api_secret,
                )
            elif account.platform_id == 2:  # Bybit
                positions = await account_data_service.get_bybit_positions(
                    account.api_key,
                    account.api_secret,
                )
            else:
                return {"error": "Unknown platform"}

            # Calculate total position size
            total_position = sum(pos.size for pos in positions)
            new_total = total_position + quantity

            # Check against limit
            if max_position_size is not None:
                exceeds_limit = new_total > max_position_size
            else:
                exceeds_limit = False

            return {
                "exceeds_limit": exceeds_limit,
                "current_position": total_position,
                "proposed_quantity": quantity,
                "new_total": new_total,
                "max_position_size": max_position_size,
                "account_id": str(account.account_id),
            }

        except Exception as e:
            return {
                "error": str(e),
                "exceeds_limit": False,
            }

    async def create_risk_alert(
        self,
        db: AsyncSession,
        user_id: UUID,
        alert_level: str,
        alert_message: str,
        expire_minutes: int = 5,
    ) -> RiskAlert:
        """Create a risk alert in database

        Args:
            db: Database session
            user_id: User to alert
            alert_level: Alert level (warning, danger, info)
            alert_message: Alert message
            expire_minutes: Minutes until alert expires

        Returns:
            Created RiskAlert object
        """
        expire_time = datetime.utcnow() + timedelta(minutes=expire_minutes)

        alert = RiskAlert(
            user_id=user_id,
            alert_level=alert_level,
            alert_message=alert_message,
            expire_time=expire_time,
        )

        db.add(alert)
        await db.commit()
        await db.refresh(alert)

        # Send WebSocket notification
        await manager.send_risk_alert(
            str(user_id),
            {
                "alert_id": str(alert.alert_id),
                "level": alert_level,
                "message": alert_message,
                "create_time": alert.create_time.isoformat(),
                "expire_time": expire_time.isoformat(),
            },
        )

        return alert

    async def get_active_alerts(
        self,
        db: AsyncSession,
        user_id: UUID,
    ) -> List[RiskAlert]:
        """Get active risk alerts for user

        Args:
            db: Database session
            user_id: User ID

        Returns:
            List of active alerts
        """
        result = await db.execute(
            select(RiskAlert).where(
                RiskAlert.user_id == user_id,
                RiskAlert.expire_time > datetime.utcnow(),
            )
        )
        return result.scalars().all()

    async def clear_expired_alerts(
        self,
        db: AsyncSession,
    ):
        """Clear expired risk alerts from database

        Args:
            db: Database session
        """
        result = await db.execute(
            select(RiskAlert).where(
                RiskAlert.expire_time <= datetime.utcnow(),
            )
        )
        expired_alerts = result.scalars().all()

        for alert in expired_alerts:
            await db.delete(alert)

        await db.commit()

    async def activate_emergency_stop(self):
        """Activate emergency stop - prevents all trading"""
        self.emergency_stop_active = True
        redis_client = await self._get_redis()
        await redis_client.set("emergency_stop", "1", ex=3600)  # 1 hour expiry

    async def deactivate_emergency_stop(self):
        """Deactivate emergency stop - allows trading"""
        self.emergency_stop_active = False
        redis_client = await self._get_redis()
        await redis_client.delete("emergency_stop")

    async def is_emergency_stop_active(self) -> bool:
        """Check if emergency stop is active

        Returns:
            True if emergency stop is active
        """
        redis_client = await self._get_redis()
        stop_status = await redis_client.get("emergency_stop")
        return stop_status == b"1" or self.emergency_stop_active

    async def perform_comprehensive_risk_check(
        self,
        db: AsyncSession,
        user_id: UUID,
        binance_account: Account,
        bybit_account: Account,
        quantity: float,
        strategy_config: Optional[StrategyConfig] = None,
    ) -> Dict[str, Any]:
        """Perform comprehensive risk check before trade execution

        Args:
            db: Database session
            user_id: User ID
            binance_account: Binance account
            bybit_account: Bybit account
            quantity: Proposed order quantity
            strategy_config: Strategy configuration (optional)

        Returns:
            Dict with risk check results and whether trading is allowed
        """
        checks = {}
        alerts = []
        trading_allowed = True

        # Check emergency stop
        emergency_stop = await self.is_emergency_stop_active()
        checks["emergency_stop"] = emergency_stop

        if emergency_stop:
            trading_allowed = False
            alerts.append({
                "level": "danger",
                "message": "Emergency stop is active - all trading disabled",
            })

        # Check MT5 stuck
        if strategy_config:
            mt5_threshold = strategy_config.mt5_stuck_threshold
        else:
            mt5_threshold = 5

        mt5_check = await self.check_mt5_stuck(threshold=mt5_threshold)
        checks["mt5_stuck"] = mt5_check

        if mt5_check.get("is_stuck"):
            trading_allowed = False
            alerts.append({
                "level": "danger",
                "message": f"MT5 data stuck - price unchanged for {mt5_check['counter']} checks",
            })
            await self.create_risk_alert(
                db,
                user_id,
                "danger",
                f"MT5 data stuck - price unchanged for {mt5_check['counter']} checks",
            )

        # Check Binance account risk
        binance_risk = await self.check_account_risk(binance_account, max_risk_ratio=80.0)
        checks["binance_risk"] = binance_risk

        if binance_risk.get("is_high_risk"):
            trading_allowed = False
            alerts.append({
                "level": "danger",
                "message": f"Binance account risk ratio too high: {binance_risk['risk_ratio']:.2f}%",
            })
            await self.create_risk_alert(
                db,
                user_id,
                "danger",
                f"Binance account risk ratio too high: {binance_risk['risk_ratio']:.2f}%",
            )

        # Check Bybit account risk
        bybit_risk = await self.check_account_risk(bybit_account, max_risk_ratio=80.0)
        checks["bybit_risk"] = bybit_risk

        if bybit_risk.get("is_high_risk"):
            trading_allowed = False
            alerts.append({
                "level": "danger",
                "message": f"Bybit account risk ratio too high: {bybit_risk['risk_ratio']:.2f}%",
            })
            await self.create_risk_alert(
                db,
                user_id,
                "danger",
                f"Bybit account risk ratio too high: {bybit_risk['risk_ratio']:.2f}%",
            )

        # Check position limits (if configured)
        # For now, we'll skip this as it requires configuration

        return {
            "trading_allowed": trading_allowed,
            "checks": checks,
            "alerts": alerts,
        }


# Global instance
risk_monitor = RiskMonitor()
