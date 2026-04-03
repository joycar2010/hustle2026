"""Main FastAPI application entry point"""
import sys
import asyncio

# Fix Windows asyncio ProactorEventLoop WinError 10054 bug:
# ConnectionResetError in _call_connection_lost corrupts the event loop over time.
# SelectorEventLoop does not have this issue and is stable on Windows with uvicorn.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import gc
from app.core.config import settings
from app.core.redis_client import redis_client
from app.middleware.permission_interceptor import PermissionInterceptor
from app.api.v1 import auth, users, accounts, strategies, market, websocket, risk, automation, system, trading, test, rbac, security_components, ssl_certificates, key_management, notifications, sound_files, health, arbitrage_opportunities, system_monitor, timing_configs, proxies, mt5_clients, mt5_server, mt5_instances, mt5_agent
from app.tasks.market_data import market_streamer
from app.tasks.broadcast_tasks import account_balance_streamer, risk_metrics_streamer, mt5_connection_streamer, pending_orders_streamer, redis_status_streamer, position_streamer, binance_position_pusher
from app.tasks.redis_monitor import redis_monitor
from app.tasks.arbitrage_opportunity_scheduler import arbitrage_opportunity_scheduler
from app.tasks.timing_config_subscriber import timing_config_subscriber
from app.services.position_monitor import position_monitor
from app.services.realtime_market_service import market_data_service
from app.services.binance_ws_client import binance_ws
from app.services.strategy_status_pusher import status_pusher
from app.services.mt5_bridge import mt5_bridge
from app.services.order_recovery_service import order_recovery_service
from app.services.feishu_service import init_feishu_service
from app.services.mt5_sync_service import mt5_sync_service
from app.models.notification_config import NotificationConfig
from sqlalchemy import select
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Configure garbage collection for better memory management
gc.set_threshold(700, 10, 10)  # More aggressive garbage collection

# Global initialization state
app_state = {
    "redis_connected": False,
    "feishu_initialized": False,
    "market_services_ready": False,
    "mt5_services_ready": False,
    "order_recovery_done": False,
    "init_complete": False,
    "init_progress": 0,
    "init_errors": []
}


async def periodic_memory_cleanup():
    """Periodic memory cleanup task"""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        gc.collect()
        logger.debug("Periodic garbage collection completed")


async def init_redis_and_feishu():
    """Initialize Redis and Feishu service (fast, keep synchronous)"""
    try:
        await redis_client.connect()
        await redis_monitor.start()
        await timing_config_subscriber.start()
        app_state["redis_connected"] = True
        logger.info("Redis connected successfully")

        # Initialize Feishu service from database config
        logger.info("Initializing Feishu service from database...")
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(NotificationConfig).filter(
                        NotificationConfig.service_type == 'feishu',
                        NotificationConfig.is_enabled == True
                    )
                )
                feishu_config = result.scalar_one_or_none()

                if feishu_config and feishu_config.config_data:
                    app_id = feishu_config.config_data.get('app_id')
                    app_secret = feishu_config.config_data.get('app_secret')

                    if app_id and app_secret:
                        init_feishu_service(app_id, app_secret)
                        logger.info("Feishu service initialized successfully")
                        app_state["feishu_initialized"] = True
                else:
                    logger.info("Feishu service not enabled or not configured")
                    app_state["feishu_initialized"] = True
        except Exception as e:
            logger.error(f"Failed to initialize Feishu service: {e}")
            app_state["init_errors"].append(f"Feishu init failed: {str(e)}")
            app_state["feishu_initialized"] = True  # Mark as done even if failed
    except Exception as e:
        logger.error(f"Redis/Feishu initialization failed: {e}")
        app_state["init_errors"].append(f"Redis init failed: {str(e)}")


async def init_market_services():
    """Initialize market data services (async, non-blocking)"""
    try:
        logger.info("Starting market services initialization...")
        binance_ws.start()
        await market_streamer.start()
        await market_data_service.start()
        await status_pusher.start()
        await arbitrage_opportunity_scheduler.start()  # 启动套利机会调度器
        app_state["market_services_ready"] = True
        logger.info("Market services initialized successfully")
    except Exception as e:
        logger.error(f"Market services initialization failed: {e}")
        app_state["init_errors"].append(f"Market services failed: {str(e)}")
        app_state["market_services_ready"] = True  # Mark as done to not block


async def init_mt5_and_monitoring():
    """Initialize MT5 and monitoring services (async, non-blocking)"""
    try:
        logger.info("Starting MT5 and monitoring services...")
        await account_balance_streamer.start()
        await risk_metrics_streamer.start()
        await mt5_connection_streamer.start()
        await pending_orders_streamer.start()
        await redis_status_streamer.start()
        await position_streamer.start()   # 实时持仓广播，1秒1次
        await binance_position_pusher.start()  # Binance User Data Stream，<100ms 持仓更新
        await mt5_bridge.start()
        await position_monitor.start_monitoring()
        await mt5_sync_service.start()  # 启动 MT5 状态同步服务
        app_state["mt5_services_ready"] = True
        logger.info("MT5 and monitoring services initialized successfully")
    except Exception as e:
        logger.error(f"MT5 services initialization failed: {e}")
        app_state["init_errors"].append(f"MT5 services failed: {str(e)}")
        app_state["mt5_services_ready"] = True  # Mark as done to not block


async def recover_pending_orders():
    """Recover pending orders (async, non-blocking)"""
    try:
        logger.info("Recovering pending orders...")
        recovery_result = await order_recovery_service.recover_all_pending_orders()
        logger.info(f"Order recovery completed: {recovery_result}")
        app_state["order_recovery_done"] = True
    except Exception as e:
        logger.error(f"Order recovery failed: {e}")
        app_state["init_errors"].append(f"Order recovery failed: {str(e)}")
        app_state["order_recovery_done"] = True


async def init_all_background_services():
    """Initialize all background services in parallel (non-blocking)"""
    try:
        # First initialize Redis and Feishu (fast)
        await init_redis_and_feishu()
        app_state["init_progress"] = 20

        # Then initialize other services in parallel
        await asyncio.gather(
            init_market_services(),
            init_mt5_and_monitoring(),
            recover_pending_orders(),
            return_exceptions=True
        )

        app_state["init_progress"] = 100
        app_state["init_complete"] = True
        logger.info("All background services initialized successfully")

        if app_state["init_errors"]:
            logger.warning(f"Initialization completed with errors: {app_state['init_errors']}")
    except Exception as e:
        logger.error(f"Background services initialization failed: {e}")
        app_state["init_errors"].append(f"Overall init failed: {str(e)}")
        app_state["init_complete"] = True  # Mark as complete to not block forever


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events - fast startup with async background init"""
    # Start background initialization task (non-blocking)
    init_task = asyncio.create_task(init_all_background_services())

    # Start memory cleanup task
    cleanup_task = asyncio.create_task(periodic_memory_cleanup())

    logger.info("FastAPI application started - background services initializing...")

    yield

    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Stop all services
    try:
        await binance_ws.stop()
        await market_streamer.stop()
        await account_balance_streamer.stop()
        await risk_metrics_streamer.stop()
        await mt5_connection_streamer.stop()
        await pending_orders_streamer.stop()
        await redis_status_streamer.stop()
        await position_streamer.stop()
        await binance_position_pusher.stop()
        await mt5_bridge.stop()
        await position_monitor.stop_monitoring()
        await market_data_service.stop()
        await status_pusher.stop()
        await mt5_sync_service.stop()  # 停止 MT5 状态同步服务
        await timing_config_subscriber.stop()
        await redis_monitor.stop()
        await redis_client.disconnect()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


# Create FastAPI app
app = FastAPI(
    title="Hustle XAU Arbitrage System",
    description="Cross-platform arbitrage system for Binance XAUUSDT and Bybit MT5 XAUUSD+",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS (Security: Explicit methods and headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "X-Request-ID",
        "X-Timestamp",
        "X-Nonce",
        "X-Signature"
    ],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Add permission interceptor middleware (temporarily disabled for RBAC setup)
# app.add_middleware(PermissionInterceptor, redis_client=redis_client.client)

# Add request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[REQUEST] {request.method} {request.url.path}")
    logger.info(f"[REQUEST] {request.method} {request.url.path}")
    if "mt5-clients" in request.url.path:
        print(f"[MT5-CLIENTS REQUEST] Headers: {dict(request.headers)}")
        print(f"[MT5-CLIENTS REQUEST] Method: {request.method}")
        print(f"[MT5-CLIENTS REQUEST] Path: {request.url.path}")
        logger.info(f"[MT5-CLIENTS REQUEST] Headers: {dict(request.headers)}")
        logger.info(f"[MT5-CLIENTS REQUEST] Method: {request.method}")
        logger.info(f"[MT5-CLIENTS REQUEST] Path: {request.url.path}")

    response = await call_next(request)

    if "mt5-clients" in request.url.path:
        print(f"[MT5-CLIENTS RESPONSE] Status: {response.status_code}")
        logger.info(f"[MT5-CLIENTS RESPONSE] Status: {response.status_code}")

    print(f"[RESPONSE] {request.method} {request.url.path} - Status: {response.status_code}")
    logger.info(f"[RESPONSE] {request.method} {request.url.path} - Status: {response.status_code}")
    return response


# Global exception handler to ensure CORS headers are always present
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Ensure CORS headers are included in all error responses"""
    origin = request.headers.get("origin")

    if isinstance(exc, StarletteHTTPException):
        status_code = exc.status_code
        detail = exc.detail
    else:
        status_code = 500
        detail = "Internal server error"
        logger.error(f"Unhandled exception: {exc}", exc_info=True)

    response = JSONResponse(
        status_code=status_code,
        content={"detail": detail}
    )

    # Always add CORS headers for allowed origins
    if origin and origin in settings.cors_origins_list:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response

# Include API routers
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["Accounts"])
app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["Strategies"])
app.include_router(market.router, prefix="/api/v1/market", tags=["Market Data"])
app.include_router(risk.router, prefix="/api/v1/risk", tags=["Risk Control"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["Automation"])
app.include_router(trading.router, prefix="/api/v1/trading", tags=["Trading"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(test.router, prefix="/api/v1/test", tags=["Test"])
app.include_router(rbac.router, prefix="/api/v1/rbac", tags=["RBAC权限管理"])
app.include_router(security_components.router, prefix="/api/v1/security", tags=["安全组件管理"])
app.include_router(ssl_certificates.router, prefix="/api/v1/ssl", tags=["SSL证书管理"])
app.include_router(system_monitor.router, prefix="/api/v1/monitor", tags=["系统监控"])
app.include_router(key_management.router, prefix="/api/v1/keys", tags=["密钥管理"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["通知服务"])
app.include_router(sound_files.router, prefix="/api/v1", tags=["声音文件管理"])
app.include_router(timing_configs.router, prefix="/api/v1", tags=["时间配置管理"])
app.include_router(arbitrage_opportunities.router, prefix="/api/v1", tags=["套利机会"])
app.include_router(proxies.router, prefix="/api/v1", tags=["代理管理"])
app.include_router(mt5_clients.router, prefix="/api/v1", tags=["MT5客户端管理"])
app.include_router(mt5_instances.router, prefix="/api/v1", tags=["MT5实例管理"])
# app.include_router(performance.router, prefix="/api/v1/performance", tags=["性能监控"])  # Module not found
app.include_router(mt5_server.router, prefix="/api/v1", tags=["MT5服务器状态"])
app.include_router(mt5_agent.router, prefix="/api/v1/mt5-agent", tags=["MT5 Agent控制"])
app.include_router(websocket.router, prefix="/api/v1", tags=["WebSocket"])

# Mount static files for uploaded alert sounds
uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Mount sounds directory for audio files
sounds_dir = Path("/data/hustle2026/frontend/public/sounds")
sounds_dir.mkdir(parents=True, exist_ok=True)
app.mount("/sounds", StaticFiles(directory=str(sounds_dir)), name="sounds")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Hustle XAU Arbitrage System API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/init-status")
async def get_init_status():
    """Get backend initialization status - for frontend polling"""
    return {
        "redis_connected": app_state["redis_connected"],
        "feishu_initialized": app_state["feishu_initialized"],
        "market_services_ready": app_state["market_services_ready"],
        "mt5_services_ready": app_state["mt5_services_ready"],
        "order_recovery_done": app_state["order_recovery_done"],
        "init_complete": app_state["init_complete"],
        "init_progress": app_state["init_progress"],
        "init_errors": app_state["init_errors"],
        "status": "ready" if app_state["init_complete"] else "initializing"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
    )
