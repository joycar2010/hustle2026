"""健康检查API端点"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db, engine
from app.core.db_monitor import get_async_pool_status
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check():
    """基础健康检查"""
    return {
        "status": "healthy",
        "service": "hustle2026-backend"
    }


@router.get("/health/db")
async def database_health_check(db: AsyncSession = Depends(get_db)):
    """数据库健康检查

    Returns:
        dict: 数据库连接状态和连接池信息
    """
    try:
        from sqlalchemy import text
        # 测试数据库连接
        await db.execute(text("SELECT 1"))

        # 获取连接池状态
        pool_status = await get_async_pool_status(engine)

        return {
            "status": "healthy",
            "database": "connected",
            "pool": pool_status
        }
    except Exception as e:
        logger.error(f"[HEALTH] 数据库健康检查失败: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e)
        }


@router.get("/health/pool")
async def pool_status_check():
    """连接池状态检查（不占用连接）

    Returns:
        dict: 连接池详细状态
    """
    try:
        pool_status = await get_async_pool_status(engine)
        return {
            "status": "success",
            "pool": pool_status
        }
    except Exception as e:
        logger.error(f"[HEALTH] 连接池状态检查失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }
