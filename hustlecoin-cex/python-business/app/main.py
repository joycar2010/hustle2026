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
from app.api.ai_chat import router as ai_chat_router
from app.api.admin_dashboard import router as admin_dashboard_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_proxy import router as admin_proxy_router
from app.api.admin_ssl import router as admin_ssl_router
from app.api.admin_notify import router as admin_notify_router
from app.api.admin_system import router as admin_system_router
from app.api.admin_market import router as admin_market_router
from app.api.admin_rbac import router as admin_rbac_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_ai import router as admin_ai_router
from app.api.admin_ws import router as admin_ws_router
from app.api.admin_global_rules import router as admin_global_rules_router
from app.config import settings
from app.db.models import Base
from app.db.session import engine, SessionLocal
from app.middleware.auth import JWTAuthMiddleware
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

app.add_middleware(JWTAuthMiddleware)
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
app.include_router(ai_chat_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_users_router)
app.include_router(admin_proxy_router)
app.include_router(admin_ssl_router)
app.include_router(admin_notify_router)
app.include_router(admin_system_router)
app.include_router(admin_market_router)
app.include_router(admin_rbac_router)
app.include_router(admin_audit_router)
app.include_router(admin_ai_router)
app.include_router(admin_ws_router)
app.include_router(admin_global_rules_router)

ADMIN_SPA_DIR = Path(__file__).resolve().parent.parent / "static" / "admin-spa"

if ADMIN_SPA_DIR.is_dir():
    app.mount("/admin/assets", StaticFiles(directory=str(ADMIN_SPA_DIR / "assets")), name="admin-assets")

    @app.get("/admin/{full_path:path}")
    async def admin_spa_fallback(request: Request, full_path: str):
        file_path = ADMIN_SPA_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(ADMIN_SPA_DIR / "index.html"))

if SPA_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(SPA_DIR / "assets")), name="spa-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        file_path = SPA_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(SPA_DIR / "index.html"))
