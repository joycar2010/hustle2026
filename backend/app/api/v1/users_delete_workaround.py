"""
临时方案：在不修改表结构的情况下，通过 SQLAlchemy ORM 安全删除用户数据

此文件展示了如何在模型定义与数据库不匹配时，使用 ORM 查询来处理删除操作。
这是一个临时解决方案，推荐使用根治方案（修复模型定义）。

使用场景：
- 当无法立即修改数据库结构时
- 当需要保持向后兼容时
- 当模型定义与数据库存在临时不一致时
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from uuid import UUID


async def delete_user_safe(
    target_user_id: UUID,
    current_user_id: str,
    db: AsyncSession
):
    """
    安全删除用户的临时方案

    此方法不依赖于正确的模型定义，直接使用 ORM 查询来处理关联数据
    """
    from app.models.user import User
    from app.models.strategy import Strategy
    from app.models.position import Position

    # 1. 权限检查
    current_user_result = await db.execute(
        select(User).where(User.user_id == UUID(current_user_id))
    )
    current_user = current_user_result.scalar_one_or_none()

    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="当前用户未找到"
        )

    if current_user.role not in ['系统管理员', '管理员', 'admin', 'super_admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除用户"
        )

    # 2. 获取目标用户
    result = await db.execute(select(User).where(User.user_id == target_user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 3. 防止删除自己
    if target_user_id == UUID(current_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己的账户"
        )

    # 4. 使用 ORM 查询获取用户的策略 ID 列表
    strategies_result = await db.execute(
        select(Strategy.id).where(Strategy.user_id == target_user_id)
    )
    strategy_ids = [row[0] for row in strategies_result.all()]

    # 5. 删除策略性能记录
    # 方法1：使用原始 SQL（类型安全）
    if strategy_ids:
        from sqlalchemy import text
        await db.execute(
            text("DELETE FROM strategy_performance WHERE strategy_id = ANY(:ids)"),
            {"ids": strategy_ids}
        )

    # 方法2：逐个删除（更安全但较慢）
    # from app.models.strategy_performance import StrategyPerformance
    # for strategy_id in strategy_ids:
    #     await db.execute(
    #         delete(StrategyPerformance).where(
    #             StrategyPerformance.strategy_id == strategy_id
    #         )
    #     )

    # 6. 删除 positions（其他关联数据通过 cascade 自动删除）
    await db.execute(delete(Position).where(Position.user_id == target_user_id))

    # Note: Trade 和 SystemAlert 模型不存在，已移除相关导入

    # 7. 删除用户
    await db.delete(user)
    await db.commit()

    return None


# 使用示例：
# 在 users.py 的 delete_user 函数中：
#
# @router.delete("/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_user(
#     target_user_id: UUID,
#     user_id: str = Depends(get_current_user_id),
#     db: AsyncSession = Depends(get_db),
# ):
#     """Delete a user (admin only)"""
#     try:
#         await delete_user_safe(target_user_id, user_id, db)
#         return None
#     except HTTPException:
#         raise
#     except Exception as e:
#         await db.rollback()
#         import logging
#         logger = logging.getLogger(__name__)
#         logger.error(f"Failed to delete user {target_user_id}: {e}", exc_info=True)
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"删除用户失败: {str(e)}"
#         )
