"""数据库连接池监控模块"""
import time
import logging
from sqlalchemy import event
from sqlalchemy.pool import Pool

logger = logging.getLogger("db_pool_monitor")


def setup_db_monitor(engine):
    """监控数据库连接池状态

    Args:
        engine: SQLAlchemy引擎实例
    """

    @event.listens_for(engine.sync_engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        """连接创建时触发"""
        connection_id = id(dbapi_connection)
        connection_record.info['connect_time'] = time.time()
        logger.info(
            f"[DB_POOL] 创建数据库连接 - "
            f"连接ID: {connection_id}, "
            f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @event.listens_for(engine.sync_engine, "close")
    def on_close(dbapi_connection, connection_record):
        """连接关闭时触发"""
        connection_id = id(dbapi_connection)
        connect_time = connection_record.info.get('connect_time', 0)
        duration = time.time() - connect_time if connect_time else 0
        logger.info(
            f"[DB_POOL] 关闭数据库连接 - "
            f"连接ID: {connection_id}, "
            f"存活时长: {duration:.2f}秒, "
            f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    @event.listens_for(engine.sync_engine, "checkout")
    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        """从连接池获取连接时触发"""
        pool = engine.pool
        logger.debug(
            f"[DB_POOL] 获取连接 - "
            f"连接池大小: {pool.size()}, "
            f"已签出: {pool.checkedout()}, "
            f"溢出: {pool.overflow()}, "
            f"可用: {pool.size() - pool.checkedout()}"
        )

        # 警告：连接池接近饱和
        if pool.checkedout() >= pool.size() * 0.8:
            logger.warning(
                f"[DB_POOL] ⚠️ 连接池使用率过高！"
                f"已使用: {pool.checkedout()}/{pool.size()}, "
                f"溢出: {pool.overflow()}"
            )

    @event.listens_for(engine.sync_engine, "checkin")
    def on_checkin(dbapi_connection, connection_record):
        """连接归还到连接池时触发"""
        pool = engine.pool
        logger.debug(
            f"[DB_POOL] 归还连接 - "
            f"连接池大小: {pool.size()}, "
            f"已签出: {pool.checkedout()}, "
            f"溢出: {pool.overflow()}"
        )

    logger.info("[DB_POOL] 数据库连接池监控已启用")


def get_pool_status(engine) -> dict:
    """获取连接池当前状态

    Args:
        engine: SQLAlchemy引擎实例

    Returns:
        dict: 连接池状态信息
    """
    try:
        pool = engine.pool
        return {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "available": pool.size() - pool.checkedout(),
            "max_overflow": pool._max_overflow,
            "timeout": pool._timeout,
            "recycle": pool._recycle,
            "usage_rate": f"{(pool.checkedout() / pool.size() * 100):.1f}%",
            "status": "healthy" if pool.checkedout() < pool.size() * 0.8 else "warning"
        }
    except Exception as e:
        logger.error(f"[DB_POOL] 获取连接池状态失败: {e}")
        return {"error": str(e)}


async def get_async_pool_status(engine) -> dict:
    """获取异步连接池当前状态

    Args:
        engine: SQLAlchemy异步引擎实例

    Returns:
        dict: 连接池状态信息
    """
    try:
        pool = engine.pool
        size = pool.size()
        checked_out = pool.checkedout()
        overflow = pool.overflow()

        return {
            "pool_size": size,
            "checked_out": checked_out,
            "overflow": overflow,
            "available": size - checked_out,
            "max_overflow": pool._max_overflow,
            "timeout": pool._timeout,
            "recycle": pool._recycle,
            "usage_rate": f"{(checked_out / size * 100):.1f}%" if size > 0 else "0%",
            "status": "healthy" if checked_out < size * 0.8 else "warning"
        }
    except Exception as e:
        logger.error(f"[DB_POOL] 获取异步连接池状态失败: {e}")
        return {"error": str(e)}
