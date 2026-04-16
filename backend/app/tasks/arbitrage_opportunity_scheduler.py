"""
套利机会数据定时任务
每天自动提取可套利数据并清理旧数据
"""
import asyncio
import logging
from datetime import datetime
from app.core.database import AsyncSessionLocal
from app.services.arbitrage_opportunity_service import arbitrage_opportunity_service

logger = logging.getLogger(__name__)


class ArbitrageOpportunityScheduler:
    """套利机会数据定时调度器"""

    def __init__(self):
        self.running = False
        self.task = None

    async def start(self):
        """启动定时任务"""
        if self.running:
            logger.warning("Arbitrage opportunity scheduler already running")
            return

        self.running = True
        self.task = asyncio.create_task(self._schedule_loop())
        logger.info("Arbitrage opportunity scheduler started")

    async def stop(self):
        """停止定时任务"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Arbitrage opportunity scheduler stopped")

    async def _schedule_loop(self):
        """定时任务循环"""
        while self.running:
            try:
                # 每小时执行一次数据提取
                await self._extract_opportunities()

                # 每天凌晨2点执行数据清理
                now = datetime.now()
                if now.hour == 2 and now.minute < 10:
                    await self._cleanup_old_data()

                # 等待10分钟
                await asyncio.sleep(600)

            except Exception as e:
                logger.error(f"Error in arbitrage opportunity scheduler: {e}", exc_info=True)
                await asyncio.sleep(60)  # 出错后等待1分钟再继续

    async def _extract_opportunities(self):
        """提取套利机会数据"""
        try:
            async with AsyncSessionLocal() as db:
                result = await arbitrage_opportunity_service.extract_opportunities(db)
                logger.info(f"Extracted arbitrage opportunities: {result}")
        except Exception as e:
            logger.error(f"Error extracting opportunities: {e}", exc_info=True)

    async def _cleanup_old_data(self):
        """清理旧数据"""
        try:
            async with AsyncSessionLocal() as db:
                # 清理超过1天的spread_records
                spread_deleted = await arbitrage_opportunity_service.cleanup_old_spread_records(db, days=1)

                # 清理超过30天的arbitrage_opportunities
                opp_deleted = await arbitrage_opportunity_service.cleanup_old_opportunities(db, days=30)

                logger.info(f"Cleaned up old data: {spread_deleted} spread records, {opp_deleted} opportunities")
        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}", exc_info=True)


# 全局调度器实例
arbitrage_opportunity_scheduler = ArbitrageOpportunityScheduler()
