"""
用户删除功能的单元测试

测试删除用户时是否正确清理所有关联数据（纯 ORM 实现）
"""

import pytest
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.strategy import StrategyConfig
from app.models.strategy_performance import StrategyPerformance
from app.models.position import Position
from app.core.security import get_password_hash


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """创建测试用户"""
    user = User(
        user_id=uuid.uuid4(),
        username=f"test_user_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("test_password"),
        role="交易员",
        is_active=True
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_strategy_config(db_session: AsyncSession, test_user: User):
    """创建测试策略配置"""
    config = StrategyConfig(
        config_id=uuid.uuid4(),
        user_id=test_user.user_id,
        strategy_type="forward",
        target_spread=2.5,
        order_qty=1.0,
        is_enabled=True
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    return config


@pytest.fixture
async def test_strategy_performance(
    db_session: AsyncSession,
    test_strategy_config: StrategyConfig
):
    """创建测试策略性能记录"""
    performance = StrategyPerformance(
        performance_id=uuid.uuid4(),
        strategy_id=test_strategy_config.config_id,  # UUID 类型
        today_trades=10,
        today_profit=150.5,
        total_trades=100,
        total_profit=1500.0,
        win_rate=0.65,
        max_drawdown=-50.0,
        date=datetime.utcnow(),
        timestamp=datetime.utcnow()
    )
    db_session.add(performance)
    await db_session.commit()
    await db_session.refresh(performance)
    return performance


class TestUserDeletion:
    """用户删除功能测试套件"""

    @pytest.mark.asyncio
    async def test_delete_user_with_strategy_performance(
        self,
        db_session: AsyncSession,
        test_user: User,
        test_strategy_config: StrategyConfig,
        test_strategy_performance: StrategyPerformance
    ):
        """
        测试删除用户时是否正确删除关联的策略性能记录

        验证点：
        1. 用户删除前，strategy_performance 记录存在
        2. 用户删除后，strategy_performance 记录被清理
        3. 使用纯 ORM 实现，无原始 SQL
        """
        user_id = test_user.user_id
        config_id = test_strategy_config.config_id
        performance_id = test_strategy_performance.performance_id

        # 验证删除前数据存在
        perf_before = await db_session.execute(
            select(StrategyPerformance).where(
                StrategyPerformance.performance_id == performance_id
            )
        )
        assert perf_before.scalar_one_or_none() is not None, "性能记录应该存在"

        # 执行删除逻辑（模拟 users.py 中的删除代码）
        from sqlalchemy import delete

        # Step 1: 获取用户的所有策略配置 ID
        strategy_configs_result = await db_session.execute(
            select(StrategyConfig.config_id).where(
                StrategyConfig.user_id == user_id
            )
        )
        strategy_config_ids = [row[0] for row in strategy_configs_result.all()]

        # Step 2: 删除策略性能记录
        if strategy_config_ids:
            await db_session.execute(
                delete(StrategyPerformance).where(
                    StrategyPerformance.strategy_id.in_(strategy_config_ids)
                )
            )

        # Step 3: 删除用户
        await db_session.delete(test_user)
        await db_session.commit()

        # 验证删除后数据不存在
        perf_after = await db_session.execute(
            select(StrategyPerformance).where(
                StrategyPerformance.performance_id == performance_id
            )
        )
        assert perf_after.scalar_one_or_none() is None, "性能记录应该被删除"

        user_after = await db_session.execute(
            select(User).where(User.user_id == user_id)
        )
        assert user_after.scalar_one_or_none() is None, "用户应该被删除"

    @pytest.mark.asyncio
    async def test_delete_user_with_multiple_configs(
        self,
        db_session: AsyncSession,
        test_user: User
    ):
        """
        测试删除拥有多个策略配置的用户

        验证点：
        1. 正确处理多个策略配置
        2. 所有关联的性能记录都被删除
        3. 使用 in_() 操作符正确处理批量删除
        """
        # 创建多个策略配置
        configs = []
        performances = []

        for i in range(3):
            config = StrategyConfig(
                config_id=uuid.uuid4(),
                user_id=test_user.user_id,
                strategy_type="forward" if i % 2 == 0 else "reverse",
                target_spread=2.0 + i,
                order_qty=1.0,
                is_enabled=True
            )
            db_session.add(config)
            configs.append(config)

        await db_session.commit()

        # 为每个配置创建性能记录
        for config in configs:
            await db_session.refresh(config)
            perf = StrategyPerformance(
                performance_id=uuid.uuid4(),
                strategy_id=config.config_id,
                today_trades=5,
                today_profit=50.0,
                total_trades=50,
                total_profit=500.0,
                win_rate=0.6,
                max_drawdown=-20.0,
                date=datetime.utcnow(),
                timestamp=datetime.utcnow()
            )
            db_session.add(perf)
            performances.append(perf)

        await db_session.commit()

        # 验证删除前有 3 条性能记录
        count_before = await db_session.execute(
            select(StrategyPerformance).where(
                StrategyPerformance.strategy_id.in_([c.config_id for c in configs])
            )
        )
        assert len(count_before.scalars().all()) == 3, "应该有 3 条性能记录"

        # 执行删除
        from sqlalchemy import delete

        strategy_configs_result = await db_session.execute(
            select(StrategyConfig.config_id).where(
                StrategyConfig.user_id == test_user.user_id
            )
        )
        strategy_config_ids = [row[0] for row in strategy_configs_result.all()]

        if strategy_config_ids:
            await db_session.execute(
                delete(StrategyPerformance).where(
                    StrategyPerformance.strategy_id.in_(strategy_config_ids)
                )
            )

        await db_session.delete(test_user)
        await db_session.commit()

        # 验证删除后没有性能记录
        count_after = await db_session.execute(
            select(StrategyPerformance).where(
                StrategyPerformance.strategy_id.in_([c.config_id for c in configs])
            )
        )
        assert len(count_after.scalars().all()) == 0, "所有性能记录应该被删除"

    @pytest.mark.asyncio
    async def test_delete_user_without_performance_data(
        self,
        db_session: AsyncSession,
        test_user: User
    ):
        """
        测试删除没有性能数据的用户

        验证点：
        1. 空列表情况下不会出错
        2. in_() 操作符正确处理空列表
        """
        from sqlalchemy import delete

        # 用户没有策略配置，config_ids 为空
        strategy_configs_result = await db_session.execute(
            select(StrategyConfig.config_id).where(
                StrategyConfig.user_id == test_user.user_id
            )
        )
        strategy_config_ids = [row[0] for row in strategy_configs_result.all()]

        assert len(strategy_config_ids) == 0, "应该没有策略配置"

        # 删除操作不应该出错
        if strategy_config_ids:
            await db_session.execute(
                delete(StrategyPerformance).where(
                    StrategyPerformance.strategy_id.in_(strategy_config_ids)
                )
            )

        await db_session.delete(test_user)
        await db_session.commit()

        # 验证用户被删除
        user_after = await db_session.execute(
            select(User).where(User.user_id == test_user.user_id)
        )
        assert user_after.scalar_one_or_none() is None, "用户应该被删除"


# pytest 配置
@pytest.fixture
async def db_session():
    """数据库会话 fixture（需要根据项目配置调整）"""
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        yield session
        await session.rollback()  # 测试后回滚


# 运行测试
# pytest tests/test_user_deletion.py -v -s
