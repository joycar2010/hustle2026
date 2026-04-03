"""Timing Configuration Service"""
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from app.models.timing_config import TimingConfig, TimingConfigHistory, TimingConfigTemplate
from app.schemas.timing_config import TimingConfigCreate, TimingConfigUpdate, TimingConfigTemplateCreate
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


class TimingConfigService:
    """Service for managing timing configurations with three-tier inheritance"""

    REDIS_KEY_PREFIX = "timing_config"
    RELOAD_CHANNEL = "timing_config:reload"
    CACHE_TTL = 3600  # 1 hour

    @staticmethod
    async def get_all_configs(db: AsyncSession) -> List[TimingConfig]:
        """Get all timing configurations"""
        result = await db.execute(select(TimingConfig))
        return result.scalars().all()

    @staticmethod
    async def get_config_by_id(db: AsyncSession, config_id: int) -> Optional[TimingConfig]:
        """Get timing configuration by ID"""
        result = await db.execute(
            select(TimingConfig).where(TimingConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_effective_config(
        db: AsyncSession,
        strategy_type: Optional[str] = None,
        instance_id: Optional[int] = None
    ) -> Dict:
        """
        Get effective configuration with three-tier inheritance:
        instance > strategy_type > global
        """
        # Try cache first
        cache_key = TimingConfigService._get_cache_key(strategy_type, instance_id)
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        # Query database with inheritance logic
        configs = {}

        # 1. Get global config
        result = await db.execute(
            select(TimingConfig).where(
                and_(
                    TimingConfig.config_level == 'global',
                    TimingConfig.strategy_type.is_(None),
                    TimingConfig.strategy_instance_id.is_(None)
                )
            )
        )
        global_config = result.scalars().first()
        if global_config:
            configs = TimingConfigService._model_to_dict(global_config)

        # 2. Override with strategy_type config if exists
        if strategy_type:
            result = await db.execute(
                select(TimingConfig).where(
                    and_(
                        TimingConfig.config_level == 'strategy_type',
                        TimingConfig.strategy_type == strategy_type,
                        TimingConfig.strategy_instance_id.is_(None)
                    )
                )
            )
            type_config = result.scalars().first()
            if type_config:
                configs.update(TimingConfigService._model_to_dict(type_config))

        # 3. Override with instance config if exists
        if instance_id:
            result = await db.execute(
                select(TimingConfig).where(
                    and_(
                        TimingConfig.config_level == 'instance',
                        TimingConfig.strategy_instance_id == instance_id
                    )
                )
            )
            instance_config = result.scalars().first()
            if instance_config:
                configs.update(TimingConfigService._model_to_dict(instance_config))

        # Cache the result
        await redis_client.set(
            cache_key,
            json.dumps(configs),
            ex=TimingConfigService.CACHE_TTL
        )

        return configs

    @staticmethod
    async def create_config(
        db: AsyncSession,
        config_data: TimingConfigCreate,
        user_id: int
    ) -> TimingConfig:
        """Create new timing configuration"""
        config = TimingConfig(
            **config_data.model_dump(),
            created_by=user_id
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)

        # Clear cache and notify
        await TimingConfigService._clear_cache_and_notify(
            config.config_level,
            config.strategy_type,
            config.strategy_instance_id
        )

        return config

    @staticmethod
    async def update_config(
        db: AsyncSession,
        config_id: int,
        config_data: TimingConfigUpdate,
        user_id: Optional[int] = None
    ) -> Optional[TimingConfig]:
        """Update timing configuration and create history record"""
        config = await TimingConfigService.get_config_by_id(db, config_id)
        if not config:
            return None

        # Create history record before updating
        config_dict = TimingConfigService._model_to_dict(config)
        history = TimingConfigHistory(
            config_id=config.id,
            config_level=config.config_level,
            strategy_type=config.strategy_type,
            strategy_instance_id=config.strategy_instance_id,
            config_data=config_dict,
            template=config.template,
            created_by=user_id
        )
        db.add(history)

        # Update only provided fields
        update_data = config_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(config, key, value)

        # Update timestamp
        config.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(config)

        # Clear cache and notify
        await TimingConfigService._clear_cache_and_notify(
            config.config_level,
            config.strategy_type,
            config.strategy_instance_id
        )

        return config

    @staticmethod
    async def delete_config(db: AsyncSession, config_id: int) -> bool:
        """Delete timing configuration"""
        config = await TimingConfigService.get_config_by_id(db, config_id)
        if not config:
            return False

        # Store info for cache clearing
        config_level = config.config_level
        strategy_type = config.strategy_type
        instance_id = config.strategy_instance_id

        await db.delete(config)
        await db.commit()

        # Clear cache and notify
        await TimingConfigService._clear_cache_and_notify(
            config_level,
            strategy_type,
            instance_id
        )

        return True

    @staticmethod
    def _model_to_dict(config: TimingConfig) -> Dict:
        """Convert model to dictionary (excluding metadata)"""
        return {
            "trigger_check_interval": config.trigger_check_interval,
            "opening_trigger_count": config.opening_trigger_count,
            "closing_trigger_count": config.closing_trigger_count,
            "binance_timeout": config.binance_timeout,
            "bybit_timeout": config.bybit_timeout,
            "order_check_interval": config.order_check_interval,
            "spread_check_interval": config.spread_check_interval,
            "mt5_deal_sync_wait": config.mt5_deal_sync_wait,
            "api_spam_prevention_delay": config.api_spam_prevention_delay,
            "delayed_single_leg_check_delay": config.delayed_single_leg_check_delay,
            "delayed_single_leg_second_check_delay": config.delayed_single_leg_second_check_delay,
            "api_retry_times": config.api_retry_times,
            "api_retry_delay": config.api_retry_delay,
            "max_binance_limit_retries": config.max_binance_limit_retries,
            "open_wait_after_cancel_no_trade": config.open_wait_after_cancel_no_trade,
            "open_wait_after_cancel_part": config.open_wait_after_cancel_part,
            "close_wait_after_cancel_no_trade": config.close_wait_after_cancel_no_trade,
            "close_wait_after_cancel_part": config.close_wait_after_cancel_part,
            "status_polling_interval": config.status_polling_interval,
            "debounce_delay": config.debounce_delay,
        }

    @staticmethod
    def _get_cache_key(strategy_type: Optional[str], instance_id: Optional[int]) -> str:
        """Generate Redis cache key"""
        if instance_id:
            return f"{TimingConfigService.REDIS_KEY_PREFIX}:instance:{instance_id}"
        elif strategy_type:
            return f"{TimingConfigService.REDIS_KEY_PREFIX}:strategy_type:{strategy_type}"
        else:
            return f"{TimingConfigService.REDIS_KEY_PREFIX}:global"

    @staticmethod
    async def _clear_cache_and_notify(
        config_level: str,
        strategy_type: Optional[str],
        instance_id: Optional[int]
    ):
        """Clear cache and publish reload notification"""
        # Clear specific cache
        cache_key = TimingConfigService._get_cache_key(strategy_type, instance_id)
        await redis_client.delete(cache_key)

        # If updating strategy_type or global, clear all related caches
        if config_level == 'global':
            # Clear all caches
            pattern = f"{TimingConfigService.REDIS_KEY_PREFIX}:*"
            # Note: In production, use SCAN instead of KEYS
            await redis_client.delete(pattern)
        elif config_level == 'strategy_type' and strategy_type:
            # Clear strategy_type and all its instances
            await redis_client.delete(f"{TimingConfigService.REDIS_KEY_PREFIX}:strategy_type:{strategy_type}")

        # Publish reload notification
        message = json.dumps({
            "config_level": config_level,
            "strategy_type": strategy_type,
            "instance_id": instance_id
        })
        await redis_client.publish(TimingConfigService.RELOAD_CHANNEL, message)
        logger.info(f"Published timing config reload notification: {message}")

    @staticmethod
    async def get_config_history(
        db: AsyncSession,
        strategy_type: str,
        limit: int = 20
    ) -> List[TimingConfigHistory]:
        """Get configuration history for a strategy type"""
        result = await db.execute(
            select(TimingConfigHistory)
            .where(TimingConfigHistory.strategy_type == strategy_type)
            .order_by(desc(TimingConfigHistory.created_at))
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get_custom_templates(
        db: AsyncSession,
        strategy_type: str
    ) -> List[TimingConfigTemplate]:
        """Get custom templates for a strategy type"""
        result = await db.execute(
            select(TimingConfigTemplate)
            .where(TimingConfigTemplate.strategy_type == strategy_type)
            .order_by(desc(TimingConfigTemplate.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def create_custom_template(
        db: AsyncSession,
        template_data: TimingConfigTemplateCreate,
        user_id: Optional[str] = None
    ) -> TimingConfigTemplate:
        """Create a custom template"""
        template = TimingConfigTemplate(
            strategy_type=template_data.strategy_type,
            name=template_data.name,
            description=template_data.description,
            config_data=template_data.config_data,
            created_by=user_id
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def delete_custom_template(
        db: AsyncSession,
        template_id: int,
        user_id: Optional[str] = None
    ) -> bool:
        """Delete a custom template"""
        result = await db.execute(
            select(TimingConfigTemplate)
            .where(TimingConfigTemplate.id == template_id)
        )
        template = result.scalar_one_or_none()

        if not template:
            return False

        # Optional: Check if user owns the template
        # if user_id and template.created_by != user_id:
        #     return False

        await db.delete(template)
        await db.commit()
        return True


# Singleton instance
timing_config_service = TimingConfigService()
