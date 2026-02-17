from fastapi import APIRouter
from .auth import router as auth_router
from .users import router as users_router
from .accounts import router as accounts_router
from .platforms import router as platforms_router
from .strategy_configs import router as strategy_configs_router
from .market_data import router as market_data_router
from .arbitrage import router as arbitrage_router
from .risk_alerts import router as risk_alerts_router
from .database import router as database_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["accounts"])
api_router.include_router(platforms_router, prefix="/platforms", tags=["platforms"])
api_router.include_router(strategy_configs_router, prefix="/strategy-configs", tags=["strategy-configs"])
api_router.include_router(market_data_router, prefix="/market-data", tags=["market-data"])
api_router.include_router(arbitrage_router, prefix="/arbitrage", tags=["arbitrage"])
api_router.include_router(risk_alerts_router, prefix="/risk-alerts", tags=["risk-alerts"])
api_router.include_router(database_router, tags=["database"])
