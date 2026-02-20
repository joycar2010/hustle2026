"""Main FastAPI application entry point"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.api.v1 import auth, users, accounts, strategies, market, websocket, risk, automation
from app.tasks.market_data import market_streamer
from app.services.position_monitor import position_monitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await market_streamer.start()
    await position_monitor.start_monitoring()
    yield
    # Shutdown
    await market_streamer.stop()
    await position_monitor.stop_monitoring()


# Create FastAPI app
app = FastAPI(
    title="Hustle XAU Arbitrage System",
    description="Cross-platform arbitrage system for Binance XAUUSDT and Bybit MT5 XAUUSD.s",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["Accounts"])
app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["Strategies"])
app.include_router(market.router, prefix="/api/v1/market", tags=["Market Data"])
app.include_router(risk.router, prefix="/api/v1/risk", tags=["Risk Control"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["Automation"])
app.include_router(websocket.router, tags=["WebSocket"])


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
