"""
套利机会数据处理服务
负责从spread_records中提取可套利数据并存储到arbitrage_opportunities表
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.models.market_data import SpreadRecord
from app.models.arbitrage_opportunity import ArbitrageOpportunity
from app.models.strategy import StrategyConfig

logger = logging.getLogger(__name__)


class ArbitrageOpportunityService:
    """套利机会数据处理服务"""

    async def extract_opportunities(self, db: AsyncSession) -> Dict[str, int]:
        """
        从spread_records中提取可套利的数据点并存储到arbitrage_opportunities表

        Returns:
            统计信息字典
        """
        try:
            # 获取所有策略配置
            result = await db.execute(select(StrategyConfig))
            configs = result.scalars().all()

            if not configs:
                logger.warning("No strategy configs found")
                return {"extracted": 0, "error": "No strategy configs"}

            # 获取最新已处理的时间戳，只处理新数据
            latest_result = await db.execute(
                select(ArbitrageOpportunity.timestamp).order_by(
                    ArbitrageOpportunity.timestamp.desc()
                ).limit(1)
            )
            latest_ts = latest_result.scalar_one_or_none()

            # 如果没有历史记录，回溯24小时；否则从最新记录时间开始
            if latest_ts is None:
                cutoff_time = datetime.utcnow() - timedelta(hours=24)
            else:
                cutoff_time = latest_ts

            result = await db.execute(
                select(SpreadRecord).where(SpreadRecord.timestamp > cutoff_time)
                .order_by(SpreadRecord.timestamp.asc())
            )
            spread_records = result.scalars().all()

            logger.info(f"Found {len(spread_records)} new spread records since {cutoff_time}")

            opportunities_created = 0

            # 遍历每条记录，检查是否满足套利条件
            for record in spread_records:
                for config in configs:
                    target_spread = config.target_spread

                    # 检查正向套利机会
                    if config.strategy_type == 'forward':
                        # 正向开仓：forward_spread >= target_spread
                        if record.forward_spread >= target_spread:
                            await self._create_opportunity(
                                db, record, 'forward_open', target_spread
                            )
                            opportunities_created += 1

                        # 正向平仓：forward_spread <= -target_spread (反向点差足够大)
                        if record.forward_spread <= -target_spread:
                            await self._create_opportunity(
                                db, record, 'forward_close', target_spread
                            )
                            opportunities_created += 1

                    # 检查反向套利机会
                    elif config.strategy_type == 'reverse':
                        # 反向开仓：reverse_spread >= target_spread
                        if record.reverse_spread >= target_spread:
                            await self._create_opportunity(
                                db, record, 'reverse_open', target_spread
                            )
                            opportunities_created += 1

                        # 反向平仓：reverse_spread <= -target_spread
                        if record.reverse_spread <= -target_spread:
                            await self._create_opportunity(
                                db, record, 'reverse_close', target_spread
                            )
                            opportunities_created += 1

            await db.commit()

            logger.info(f"Extracted {opportunities_created} arbitrage opportunities")

            return {
                "extracted": opportunities_created,
                "spread_records_checked": len(spread_records),
                "configs_used": len(configs)
            }

        except Exception as e:
            logger.error(f"Error extracting opportunities: {e}", exc_info=True)
            await db.rollback()
            return {"extracted": 0, "error": str(e)}

    async def _create_opportunity(
        self,
        db: AsyncSession,
        record: SpreadRecord,
        opportunity_type: str,
        target_spread: float
    ):
        """创建套利机会记录"""
        opportunity = ArbitrageOpportunity(
            symbol=record.symbol,
            binance_bid=record.binance_bid,
            binance_ask=record.binance_ask,
            bybit_bid=record.bybit_bid,
            bybit_ask=record.bybit_ask,
            forward_spread=record.forward_spread,
            reverse_spread=record.reverse_spread,
            opportunity_type=opportunity_type,
            target_spread=target_spread,
            timestamp=record.timestamp
        )

        db.add(opportunity)

    async def cleanup_old_spread_records(self, db: AsyncSession, days: int = 1) -> int:
        """
        清理超过指定天数的spread_records数据

        Args:
            db: 数据库会话
            days: 保留天数，默认1天

        Returns:
            删除的记录数
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days)

            result = await db.execute(
                delete(SpreadRecord).where(SpreadRecord.timestamp < cutoff_time)
            )

            deleted_count = result.rowcount
            await db.commit()

            logger.info(f"Cleaned up {deleted_count} old spread records (older than {days} days)")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up spread records: {e}", exc_info=True)
            await db.rollback()
            return 0

    async def cleanup_old_opportunities(self, db: AsyncSession, days: int = 30) -> int:
        """
        清理超过指定天数的arbitrage_opportunities数据

        Args:
            db: 数据库会话
            days: 保留天数，默认30天

        Returns:
            删除的记录数
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days)

            result = await db.execute(
                delete(ArbitrageOpportunity).where(ArbitrageOpportunity.timestamp < cutoff_time)
            )

            deleted_count = result.rowcount
            await db.commit()

            logger.info(f"Cleaned up {deleted_count} old arbitrage opportunities (older than {days} days)")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up opportunities: {e}", exc_info=True)
            await db.rollback()
            return 0


# 全局服务实例
arbitrage_opportunity_service = ArbitrageOpportunityService()
