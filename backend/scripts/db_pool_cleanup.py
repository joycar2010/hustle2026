"""数据库连接池巡检脚本

定时清理异常连接，监控连接池状态
运行方式：python -m backend.scripts.db_pool_cleanup
"""
import asyncio
import time
import logging
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.database import engine, AsyncSessionLocal
from app.core.db_monitor import get_async_pool_status

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('db_pool_cleanup.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("db_pool_cleanup")


async def cleanup_db_pool():
    """清理异常数据库连接"""
    try:
        # 获取连接池状态
        pool_status = await get_async_pool_status(engine)

        logger.info(
            f"[巡检] 连接池状态 - "
            f"大小: {pool_status.get('pool_size')}, "
            f"已签出: {pool_status.get('checked_out')}, "
            f"溢出: {pool_status.get('overflow')}, "
            f"可用: {pool_status.get('available')}, "
            f"使用率: {pool_status.get('usage_rate')}, "
            f"状态: {pool_status.get('status')}"
        )

        # 警告：连接池使用率过高
        if pool_status.get('status') == 'warning':
            logger.warning(
                f"[巡检] ⚠️ 连接池使用率过高！"
                f"建议检查是否存在连接泄漏"
            )

        # 测试数据库连接
        try:
            async with AsyncSessionLocal() as session:
                await session.execute("SELECT 1")
            logger.info("[巡检] 数据库连接测试成功")
        except Exception as e:
            logger.error(f"[巡检] ❌ 数据库连接测试失败: {e}")

        # 强制回收过期连接（通过pool_recycle配置自动处理）
        # engine.pool.recycle() 在异步引擎中不可用，依赖pool_recycle参数

    except Exception as e:
        logger.error(f"[巡检] 清理连接池失败: {str(e)}", exc_info=True)


async def run_periodic_cleanup(interval_seconds=3600):
    """定期执行连接池巡检

    Args:
        interval_seconds: 巡检间隔（秒），默认3600秒=1小时
    """
    logger.info(f"[巡检] 启动连接池巡检服务，间隔: {interval_seconds}秒")

    while True:
        try:
            await cleanup_db_pool()
        except Exception as e:
            logger.error(f"[巡检] 巡检任务异常: {e}", exc_info=True)

        # 等待下一次巡检
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    # 支持命令行参数指定巡检间隔
    interval = 3600  # 默认1小时
    if len(sys.argv) > 1:
        try:
            interval = int(sys.argv[1])
            logger.info(f"[巡检] 使用自定义间隔: {interval}秒")
        except ValueError:
            logger.warning(f"[巡检] 无效的间隔参数，使用默认值: {interval}秒")

    # 运行巡检服务
    try:
        asyncio.run(run_periodic_cleanup(interval))
    except KeyboardInterrupt:
        logger.info("[巡检] 巡检服务已停止")
