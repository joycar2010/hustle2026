import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.spread import router as spread_router
from app.api.global_rules import router as global_rules_router
from app.api.fund_rules import router as fund_rules_router
from app.api.feishu import router as feishu_router
from app.api.blacklist import router as blacklist_router
from app.api.sub_account import router as sub_account_router
from app.api.master_account import router as master_account_router
from app.api.symbol import router as symbol_router
from app.api.engine_api import router as engine_router
from app.api.symbol_rules import router as symbol_rules_router
from app.api.account_symbol_rules import router as account_symbol_rules_router
from app.api.auth import router as auth_router
from app.api.coin_management import router as coin_mgmt_router
from app.api.websocket import router as ws_router
from app.config import settings
from app.db.models import Base
from app.db.session import engine, SessionLocal
from app.services.spread_reader import spread_reader
from app.services import symbol_sync

logger = logging.getLogger(__name__)

SPA_DIR = Path(__file__).resolve().parent.parent / "static" / "spa"


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


app = FastAPI(title="HustleCoin CEX-CEX", version="0.5.0", lifespan=lifespan)

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
app.include_router(symbol_rules_router)
app.include_router(account_symbol_rules_router)
app.include_router(auth_router)
app.include_router(coin_mgmt_router)
app.include_router(ws_router)

if SPA_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(SPA_DIR / "assets")), name="spa-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        file_path = SPA_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(SPA_DIR / "index.html"))
