import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
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
from app.api.auth import router as auth_router
from app.api.websocket import router as ws_router
from app.api.account_symbol_rules import router as account_symbol_rules_router
from app.api.coin_management import router as coin_management_router
from app.api.admin_users import router as admin_users_router
from app.api.admin_ssl import router as admin_ssl_router
from app.api.admin_proxy import router as admin_proxy_router
from app.api.admin_dashboard import router as admin_dashboard_router
from app.api.admin_audit import router as admin_audit_router
from app.api.admin_ws import router as admin_ws_router
from app.api.admin_notify import router as admin_notify_router
from app.api.admin_system import router as admin_system_router
from app.api.admin_ai import router as admin_ai_router
from app.api.admin_global_rules import router as admin_global_rules_router
from app.api.admin_market import router as admin_market_router
from app.api.ai_chat import router as ai_chat_router
from app.api.admin_rbac import router as admin_rbac_router
from app.api.market import router as market_router
from app.config import settings
from app.middleware.auth import JWTAuthMiddleware
from app.middleware.audit import AuditMiddleware
from app.db.models import Base
from app.db.session import engine, SessionLocal
from app.services.spread_reader import spread_reader
from app.services.balance_pusher import balance_pusher
from app.services import symbol_sync

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await spread_reader.start()
    await balance_pusher.start()

    if settings.symbol_sync_on_startup:
        try:
            db = SessionLocal()
            result = await symbol_sync.sync_symbols(db)
            logger.info(f"Startup symbol sync: {result}")
            db.close()
        except Exception as e:
            logger.warning(f"Startup symbol sync failed (non-fatal): {e}")

    yield


app = FastAPI(title="HustleCoin CEX-CEX", version="0.4.0", lifespan=lifespan)

origins = settings.allowed_origins.split(",") if settings.allowed_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)
app.add_middleware(JWTAuthMiddleware)

# User-facing API routers
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
app.include_router(auth_router)
app.include_router(ws_router)
app.include_router(account_symbol_rules_router)
app.include_router(coin_management_router)
app.include_router(market_router)

# Admin API routers
app.include_router(admin_users_router)
app.include_router(admin_ssl_router)
app.include_router(admin_proxy_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_audit_router)
app.include_router(admin_ws_router)
app.include_router(admin_notify_router)
app.include_router(admin_system_router)
app.include_router(admin_ai_router)
app.include_router(admin_global_rules_router)
app.include_router(admin_market_router)
app.include_router(admin_rbac_router)
app.include_router(ai_chat_router)

STATIC_DIR = Path(__file__).parent.parent / "static"
SPA_DIR = STATIC_DIR / "spa"
ADMIN_SPA_DIR = STATIC_DIR / "admin-spa"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if SPA_DIR.exists() and (SPA_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(SPA_DIR / "assets")), name="spa-assets")

if ADMIN_SPA_DIR.exists() and (ADMIN_SPA_DIR / "assets").exists():
    app.mount("/admin/assets", StaticFiles(directory=str(ADMIN_SPA_DIR / "assets")), name="admin-spa-assets")


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.4.0"}


@app.get("/admin/{full_path:path}")
async def serve_admin_spa(full_path: str):
    if full_path:
        file_path = (ADMIN_SPA_DIR / full_path).resolve()
        if file_path.is_file() and str(file_path).startswith(str(ADMIN_SPA_DIR.resolve())):
            return FileResponse(str(file_path))
    admin_index = ADMIN_SPA_DIR / "index.html"
    if admin_index.exists():
        return FileResponse(
            str(admin_index),
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
    return {"detail": "Admin frontend not deployed yet"}


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("ws/"):
        stripped = full_path.rstrip("/")
        if stripped != full_path:
            return RedirectResponse(url=f"/{stripped}", status_code=307)
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    spa_index = SPA_DIR / "index.html"
    if spa_index.exists():
        return FileResponse(
            str(spa_index),
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
    legacy = STATIC_DIR / "dashboard.html"
    if legacy.exists():
        return FileResponse(str(legacy))
    return RedirectResponse(url="/docs")
