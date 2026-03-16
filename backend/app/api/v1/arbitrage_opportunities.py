"""
套利机会API路由
提供基于arbitrage_opportunities表的查询和分析接口
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.arbitrage_opportunity import ArbitrageOpportunity
from app.services.arbitrage_opportunity_service import arbitrage_opportunity_service

router = APIRouter()


class OpportunityResponse(BaseModel):
    """套利机会响应模型"""
    id: str
    symbol: str
    binance_bid: float
    binance_ask: float
    bybit_bid: float
    bybit_ask: float
    forward_spread: float
    reverse_spread: float
    opportunity_type: str
    target_spread: float
    timestamp: datetime

    class Config:
        from_attributes = True


class OpportunityStatsResponse(BaseModel):
    """套利机会统计响应"""
    total_count: int
    forward_open_count: int
    forward_close_count: int
    reverse_open_count: int
    reverse_close_count: int
    avg_forward_spread: float
    avg_reverse_spread: float
    max_forward_spread: float
    max_reverse_spread: float


@router.get("/opportunities", response_model=List[OpportunityResponse])
async def get_opportunities(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    opportunity_type: Optional[str] = None,
    symbol: str = "XAUUSD",
    limit: int = Query(1000, le=10000),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    查询套利机会记录

    Args:
        start_time: 开始时间
        end_time: 结束时间
        opportunity_type: 机会类型 (forward_open, forward_close, reverse_open, reverse_close)
        symbol: 交易对
        limit: 返回记录数限制
    """
    # Convert timezone-aware datetimes to naive (database uses TIMESTAMP without timezone)
    if start_time and start_time.tzinfo is not None:
        start_time = start_time.replace(tzinfo=None)

    if end_time and end_time.tzinfo is not None:
        end_time = end_time.replace(tzinfo=None)

    # 构建查询条件
    conditions = [ArbitrageOpportunity.symbol == symbol]

    if start_time:
        conditions.append(ArbitrageOpportunity.timestamp >= start_time)

    if end_time:
        conditions.append(ArbitrageOpportunity.timestamp <= end_time)

    if opportunity_type:
        conditions.append(ArbitrageOpportunity.opportunity_type == opportunity_type)

    # 执行查询
    query = select(ArbitrageOpportunity).where(and_(*conditions)).order_by(
        ArbitrageOpportunity.timestamp.desc()
    ).limit(limit)

    result = await db.execute(query)
    opportunities = result.scalars().all()

    return [
        OpportunityResponse(
            id=str(opp.id),
            symbol=opp.symbol,
            binance_bid=opp.binance_bid,
            binance_ask=opp.binance_ask,
            bybit_bid=opp.bybit_bid,
            bybit_ask=opp.bybit_ask,
            forward_spread=opp.forward_spread,
            reverse_spread=opp.reverse_spread,
            opportunity_type=opp.opportunity_type,
            target_spread=opp.target_spread,
            timestamp=opp.timestamp
        )
        for opp in opportunities
    ]


@router.get("/opportunities/stats", response_model=OpportunityStatsResponse)
async def get_opportunity_stats(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    symbol: str = "XAUUSD",
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    获取套利机会统计信息

    Args:
        start_time: 开始时间
        end_time: 结束时间
        symbol: 交易对
    """
    # Convert timezone-aware datetimes to naive (database uses TIMESTAMP without timezone)
    if start_time and start_time.tzinfo is not None:
        start_time = start_time.replace(tzinfo=None)

    if end_time and end_time.tzinfo is not None:
        end_time = end_time.replace(tzinfo=None)

    # 构建查询条件
    conditions = [ArbitrageOpportunity.symbol == symbol]

    if start_time:
        conditions.append(ArbitrageOpportunity.timestamp >= start_time)

    if end_time:
        conditions.append(ArbitrageOpportunity.timestamp <= end_time)

    # 查询各类型数量
    type_counts = {}
    for opp_type in ['forward_open', 'forward_close', 'reverse_open', 'reverse_close']:
        type_conditions = conditions + [ArbitrageOpportunity.opportunity_type == opp_type]
        result = await db.execute(
            select(func.count()).select_from(ArbitrageOpportunity).where(and_(*type_conditions))
        )
        type_counts[opp_type] = result.scalar() or 0

    # 查询点差统计
    result = await db.execute(
        select(
            func.count(),
            func.avg(ArbitrageOpportunity.forward_spread),
            func.avg(ArbitrageOpportunity.reverse_spread),
            func.max(ArbitrageOpportunity.forward_spread),
            func.max(ArbitrageOpportunity.reverse_spread)
        ).where(and_(*conditions))
    )
    stats = result.first()

    return OpportunityStatsResponse(
        total_count=stats[0] or 0,
        forward_open_count=type_counts['forward_open'],
        forward_close_count=type_counts['forward_close'],
        reverse_open_count=type_counts['reverse_open'],
        reverse_close_count=type_counts['reverse_close'],
        avg_forward_spread=stats[1] or 0.0,
        avg_reverse_spread=stats[2] or 0.0,
        max_forward_spread=stats[3] or 0.0,
        max_reverse_spread=stats[4] or 0.0
    )


@router.post("/opportunities/extract")
async def extract_opportunities(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    手动触发从spread_records提取套利机会数据
    """
    result = await arbitrage_opportunity_service.extract_opportunities(db)
    return result


@router.post("/opportunities/cleanup")
async def cleanup_old_data(
    spread_days: int = Query(1, description="保留spread_records的天数"),
    opportunity_days: int = Query(30, description="保留arbitrage_opportunities的天数"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
):
    """
    清理旧数据
    """
    spread_deleted = await arbitrage_opportunity_service.cleanup_old_spread_records(db, spread_days)
    opp_deleted = await arbitrage_opportunity_service.cleanup_old_opportunities(db, opportunity_days)

    return {
        "spread_records_deleted": spread_deleted,
        "opportunities_deleted": opp_deleted
    }
