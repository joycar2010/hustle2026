"""Main FastAPI application entry point"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import gc
import asyncio
from app.core.config import settings
from app.core.redis_client import redis_client
from app.middleware.permission_interceptor import PermissionInterceptor
from app.api.v1 import auth, users, accounts, strategies, market, websocket, risk, automation, system, trading, test, rbac, security_components, ssl_certificates, key_management, notifications, sound_files
from app.tasks.market_data import market_streamer
from app.tasks.broadcast_tasks import account_balance_streamer, risk_metrics_streamer, mt5_connection_streamer
from app.tasks.redis_monitor import redis_monitor
from app.services.position_monitor import position_monitor
from app.services.realtime_market_service import market_data_service
from app.services.binance_ws_client import binance_ws
from app.services.strategy_status_pusher import status_pusher
from app.services.mt5_bridge import mt5_bridge

logger = logging.getLogger(__name__)

# Configure garbage collection for better memory management
gc.set_threshold(700, 10, 10)  # More aggressive garbage collection


async def periodic_memory_cleanup():
    """Periodic memory cleanup task"""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        gc.collect()
        logger.debug("Periodic garbage collection completed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await redis_client.connect()
    await redis_monitor.start()  # Start Redis monitor
    binance_ws.start()
    await market_streamer.start()
    await account_balance_streamer.start()
    await risk_metrics_streamer.start()
    await mt5_connection_streamer.start()  # Start MT5 connection monitor
    await mt5_bridge.start()  # Start MT5 real-time bridge
    await position_monitor.start_monitoring()
    await market_data_service.start()
    await status_pusher.start()  # Start strategy status pusher

    # Start memory cleanup task
    cleanup_task = asyncio.create_task(periodic_memory_cleanup())

    yield

    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await binance_ws.stop()
    await market_streamer.stop()
    await account_balance_streamer.stop()
    await risk_metrics_streamer.stop()
    await mt5_connection_streamer.stop()  # Stop MT5 connection monitor
    await mt5_bridge.stop()  # Stop MT5 real-time bridge
    await position_monitor.stop_monitoring()
    await market_data_service.stop()
    await status_pusher.stop()  # Stop strategy status pusher
    await redis_monitor.stop()  # Stop Redis monitor
    await redis_client.disconnect()


# Create FastAPI app
app = FastAPI(
    title="Hustle XAU Arbitrage System",
    description="Cross-platform arbitrage system for Binance XAUUSDT and Bybit MT5 XAUUSD.s",
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
    logger.info(f"[REQUEST] {request.method} {request.url.path}")
    response = await call_next(request)
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
app.include_router(key_management.router, prefix="/api/v1/keys", tags=["密钥管理"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["通知服务"])
app.include_router(sound_files.router, prefix="/api/v1", tags=["声音文件管理"])
app.include_router(websocket.router, tags=["WebSocket"])

# Mount static files for uploaded alert sounds
uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Mount sounds directory for audio files
sounds_dir = Path("frontend/public/sounds")
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
    )
