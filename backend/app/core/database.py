from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
from sqlalchemy.orm import sessionmaker
import logging

logger = logging.getLogger(__name__)

# Create async engine with enhanced configuration
engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=settings.ENVIRONMENT == "development",
    future=True,
    pool_size=20,  # Increased from 10 to handle streaming tasks + HTTP requests
    max_overflow=30,  # Increased from 20 for peak load
    pool_timeout=10,  # Reduced from 30 for faster failure detection
    pool_recycle=3600,  # Recycle connections every hour
    pool_pre_ping=True,  # Verify connections before using
)

# Setup async pool monitoring
@event.listens_for(engine.sync_engine, "connect")
def on_async_connect(dbapi_connection, connection_record):
    """异步连接创建监控"""
    logger.debug(f"[ASYNC_POOL] 创建连接 - ID: {id(dbapi_connection)}")

@event.listens_for(engine.sync_engine, "checkout")
def on_async_checkout(dbapi_connection, connection_record, connection_proxy):
    """异步连接获取监控"""
    pool = engine.pool
    if pool.checkedout() >= pool.size() * 0.8:
        logger.warning(
            f"[ASYNC_POOL] ⚠️ 连接池使用率过高！"
            f"已使用: {pool.checkedout()}/{pool.size()}"
        )

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Create sync engine for background tasks
sync_engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
)

# Create sync session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)

# Base class for models
Base = declarative_base()


async def get_db():
    """Dependency for getting database session with enhanced error handling"""
    session = None
    try:
        session = AsyncSessionLocal()
        yield session
        await session.commit()
    except Exception as e:
        if session:
            await session.rollback()
        logger.error(f"[DB] 数据库操作失败: {str(e)}", exc_info=True)
        raise
    finally:
        if session:
            await session.close()
            logger.debug("[DB] 数据库会话已关闭")


def get_db_context():
    """Context manager for getting database session in background tasks"""
    return AsyncSessionLocal()
