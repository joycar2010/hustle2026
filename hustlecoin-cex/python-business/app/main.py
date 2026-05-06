import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.spread import router as spread_router
from app.api.global_rules import router as global_rules_router
from app.api.fund_rules import router as fund_rules_router
from app.api.feishu import router as feishu_router
from app.api.blacklist import router as blacklist_router
from app.api.sub_account import router as sub_account_router
from app.api.master_account import router as master_account_router
from app.api.symbol import router as symbol_router
from app.api.engine_api import router as engine_router
from app.config import settings
from app.db.models import Base
from app.db.session import engine, SessionLocal
from app.services.spread_reader import spread_reader
from app.services import symbol_sync

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await spread_reader.start()

    if settings.symbol_sync_on_startup:
        try:
            db = SessionLocal()
            result = await symbol_sync.sync_symbols(db)
            logger.info(f"Startup symbol sync: {result}")
            db.close()
        except Exception as e:
            logger.warning(f"Startup symbol sync failed (non-fatal): {e}")

    yield


app = FastAPI(title="HustleCoin CEX-CEX", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(spread_router)
app.include_router(global_rules_router)
app.include_router(fund_rules_router)
app.include_router(feishu_router)
app.include_router(blacklist_router)
app.include_router(sub_account_router)
app.include_router(master_account_router)
app.include_router(symbol_router)
app.include_router(engine_router)
