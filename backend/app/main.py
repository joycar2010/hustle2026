"""Main FastAPI application entry point"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import logging.handlers
import sys
import gc
import asyncio
from app.core.config import settings

# ── Configure logging with UTF-8 to prevent UnicodeEncodeError on Windows ──
def _setup_logging():
    """Configure root logger with UTF-8 encoding for Windows compatibility."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Console handler with UTF-8 encoding
    console = logging.StreamHandler(
        stream=open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
    )
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler with UTF-8 encoding and rotation
    try:
        log_path = Path("backend.log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception:
        pass  # Don't fail startup if log file can't be created

    # Suppress noisy SQLAlchemy engine logs in production
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # 日志卫生(2026-06-11): 压制高频热路径/扇出噪声 — 仅降日志音量, 不改任何取数/交易行为
    logging.getLogger("httpx").setLevel(logging.WARNING)            # 每个HTTP请求INFO(MT5 tick轮询~58行/s)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("app.services.mt5_http_client").setLevel(logging.ERROR)   # "no tick for SYM" WARNING刷屏
    logging.getLogger("app.services.account_service").setLevel(logging.WARNING) # 余额/保证金/资金费 逐账号扇出INFO
    logging.getLogger("app.api.v1.trading").setLevel(logging.WARNING)           # Formatted/Stats/Fetching deals 重算INFO
    logging.getLogger("app.services.agent.market_snapshot").setLevel(logging.ERROR)  # testgo无go(8080)每5s重试失败WARNING

_setup_logging()
from app.core.redis_client import redis_client
from app.middleware.permission_interceptor import PermissionInterceptor
from app.api.v1 import pair_accounts, auth, users, accounts, strategies, market, websocket, risk, automation, system, trading, test, rbac, security_components, ssl_certificates, key_management, notifications, sound_files, health, arbitrage_opportunities, system_monitor, timing_configs, proxies, strategy_processes, mt5_clients, mt5_instances, mt5_server, mt5_infra, pnl, hedging, hedge_ratio, agent, site_status, hedge_records, dashboard_viz
from app.api.v1 import aicoin
from app.tasks.market_data import market_streamer
from app.tasks.broadcast_tasks import account_balance_streamer, risk_metrics_streamer, mt5_connection_streamer, pending_orders_streamer, redis_status_streamer, position_streamer, binance_position_pusher, market_state_monitor, snapshot_request_listener, market_rate_streamer, quote_divergence_monitor, pnl_fast_streamer
from app.tasks.data_request_handler import data_request_listener
from app.tasks.redis_monitor import redis_monitor
from app.tasks.system_health_monitor import system_health_monitor
from app.tasks.arbitrage_opportunity_scheduler import arbitrage_opportunity_scheduler
from app.tasks.timing_config_subscriber import timing_config_subscriber
from app.services.position_monitor import position_monitor
from app.services.realtime_market_service import market_data_service
from app.services.binance_ws_client import binance_ws
from app.services.strategy_status_pusher import status_pusher
from app.services.mt5_bridge import mt5_bridge
from app.services.order_recovery_service import order_recovery_service
from app.services.feishu_service import init_feishu_service
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
        await system_health_monitor.start()
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
        await market_state_monitor.start()  # MT5 休市/开市状态监控
        from app.services.strategy_resume_service import strategy_resume_monitor, recover_running_after_restart
        await strategy_resume_monitor.start()  # 开市后自动恢复(按对预热), 仅恢复收盘自动停的按钮
        await recover_running_after_restart()  # 重启自恢复: 把曾运行(有快照)的连续策略标记待恢复, 由上面Monitor回放, 防后端重启静默停
        from app.services.hedge_stopout_service import hedge_stopout_monitor
        await hedge_stopout_monitor.start()  # 对冲腿强平检测+单腿告警(只读)
        await binance_position_pusher.start()  # Binance User Data Stream，<100ms 持仓更新
        await snapshot_request_listener.start()  # On-demand snapshot listener (Go Hub → Python)
        await market_rate_streamer.start()  # 资金费+过夜费率 10s 广播
        await pnl_fast_streamer.start()  # 浮动盈亏(平台权威)+当日净利润 WS 快推送
        await quote_divergence_monitor.start()  # 行情背离软暂停护栏
        await data_request_listener.start()  # On-demand data request listener (PnL/FundFlow)
        await mt5_bridge.start()
        # MT5 客户端连接状态同步（每10秒更新 connection_status）
        from app.services.mt5_sync_service import mt5_sync_service
        await mt5_sync_service.start()
        await position_monitor.start_monitoring()
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
        # Load hedging pair config first (needed by market/strategy services)
        from app.services.hedging_pair_service import hedging_pair_service
        await hedging_pair_service.start_refresh()

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

        # Proxy health scheduler — rolling failure-rate window + Feishu alert on threshold.
        # Also starts the IP-expiry checker which previously was never started.
        try:
            from app.services.proxy_manager import proxy_manager
            await proxy_manager.start_health_scheduler()
            logger.info("[proxy] health scheduler started")
        except Exception as _pe:
            logger.error(f"[proxy] health scheduler failed to start: {_pe}")
        try:
            from app.tasks.proxy_expiry_checker import proxy_expiry_checker
            await proxy_expiry_checker.start()
            logger.info("[proxy] expiry checker started")
        except Exception as _pe:
            logger.error(f"[proxy] expiry checker failed to start: {_pe}")

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

    # MT5 sync service — explicit lifespan start so it survives init_mt5 failures
    try:
        from app.services.mt5_sync_service import mt5_sync_service
        if not mt5_sync_service.running:
            await mt5_sync_service.start()
            logger.info('[MT5Sync] mt5_sync_service started from lifespan')
    except Exception as _mte:
        logger.error(f'[MT5Sync] failed to start: {_mte}')

    # OpenCLAW agent loop (Shadow mode by default)
    try:
        from app.services.agent import agent_loop as openclaw_loop
        from app.services.agent import equity_fsm as openclaw_fsm
        from app.services.agent import strategy_reviewer as openclaw_reviewer
        from app.services.agent import no_profit_monitor as openclaw_npm
        from app.services.agent import balance_monitor as openclaw_bm
        from app.services.agent import leg_monitor as openclaw_legs
        openclaw_loop.start()
        openclaw_fsm.start()
        openclaw_npm.start()
        openclaw_bm.start()
        from app.services.agent.balance_monitor import start_model_refresh
        start_model_refresh()
        openclaw_reviewer.start()
        from app.services.agent import ladder_advisor as openclaw_ladder_advisor
        openclaw_ladder_advisor.start()  # 阶梯自动调参(env LADDER_ADVISOR_ENABLED 默认off)
        openclaw_legs.start()
        logger.info('[OpenCLAW] agent loop + equity FSM + no-profit + balance + reviewer + leg_monitor scheduled')
    except Exception as e:
        logger.error(f'[OpenCLAW] failed to start agent: {e}')

    # WS-based dashboard stream (push user.accounts.{uid} every 5s)
    try:
        from app.services import dashboard_stream
        dashboard_stream.start()
        logger.info('[dashboard_stream] started')
    except Exception as e:
        logger.error(f'[dashboard_stream] start err: {e}')

    # PnL 缓存预热(20260621): 为有收益关联的 owner 预算 merged 视图缓存, 消除"首访35s"。
    try:
        from app.api.v1.pnl import prewarm_loop as _pnl_prewarm
        pnl_prewarm_task = asyncio.create_task(_pnl_prewarm())
        app_state['pnl_prewarm_task'] = pnl_prewarm_task
        logger.info('[PnL-prewarm] task scheduled')
    except Exception as e:
        logger.error(f'[PnL-prewarm] failed to start: {e}')

    # Sub-account: daily NAV snapshot scheduler (00:05 Asia/Shanghai)
    try:
        from app.services.subaccount_snapshot_scheduler import daily_snapshot_loop
        nav_snapshot_task = asyncio.create_task(daily_snapshot_loop())
        app_state['nav_snapshot_task'] = nav_snapshot_task
        logger.info('[nav-scheduler] daily snapshot task scheduled')
    except Exception as e:
        logger.error(f'[nav-scheduler] failed to start: {e}')

    # Restore saved push stream intervals from DB
    try:
        from app.api.v1.system import restore_push_stream_intervals
        await restore_push_stream_intervals()
    except Exception as e:
        logger.error(f'[push-intervals] restore on startup failed: {e}')

    logger.info("FastAPI application started - background services initializing...")

    yield

    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Stop NAV scheduler
    _nst = app_state.get('nav_snapshot_task')
    if _nst:
        _nst.cancel()
        try:
            await _nst
        except asyncio.CancelledError:
            pass

    # Stop OpenCLAW
    try:
        from app.services.agent import agent_loop as openclaw_loop
        from app.services.agent import equity_fsm as openclaw_fsm
        from app.services.agent import strategy_reviewer as openclaw_reviewer
        from app.services.agent import no_profit_monitor as openclaw_npm
        from app.services.agent import balance_monitor as openclaw_bm
        from app.services.agent import leg_monitor as openclaw_legs
        await openclaw_loop.stop()
        await openclaw_fsm.stop()
        await openclaw_reviewer.stop()
        try:
            from app.services.agent import ladder_advisor as _lad
            await _lad.stop()
        except Exception:
            pass
        await openclaw_npm.stop()
        await openclaw_bm.stop()
        from app.services.agent.balance_monitor import stop_model_refresh
        await stop_model_refresh()
        await openclaw_legs.stop()
        try:
            from app.services import dashboard_stream
            await dashboard_stream.stop()
        except Exception:
            pass
    except Exception as e:
        logger.error(f'[OpenCLAW] stop error: {e}')

    # Stop all services
    try:
        from app.services.mt5_sync_service import mt5_sync_service as _mts
        await _mts.stop()
    except Exception:
        pass

    try:
        from app.services.hedging_pair_service import hedging_pair_service
        await hedging_pair_service.stop()
        await binance_ws.stop()
        await market_streamer.stop()
        await account_balance_streamer.stop()
        await risk_metrics_streamer.stop()
        await mt5_connection_streamer.stop()
        await market_state_monitor.stop()
        await pending_orders_streamer.stop()
        await redis_status_streamer.stop()
        await position_streamer.stop()
        await binance_position_pusher.stop()
        await snapshot_request_listener.stop()
        await data_request_listener.stop()
        await mt5_bridge.stop()
        await position_monitor.stop_monitoring()
        await market_data_service.stop()
        await status_pusher.stop()
        await timing_config_subscriber.stop()
        await system_health_monitor.stop()
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
async def subaccount_write_guard(request: Request, call_next):
    """Sub-accounts are view-only. Reject any non-GET except auth + sub-self
    profile reads. Auth dependency in target endpoints will run before/after,
    but we short-circuit here to keep the rule centralized."""
    method = request.method.upper()
    path = request.url.path
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return await call_next(request)
    ALLOW_PREFIX = (
        '/api/v1/auth/',          # login / refresh / logout
        '/api/v1/users/me/avatar',  # cosmetic
        '/ws',
    )
    if any(path.startswith(x) for x in ALLOW_PREFIX):
        return await call_next(request)

    # Need bearer token to know if caller is a sub. Anonymous → let downstream 401.
    auth = request.headers.get('authorization', '')
    if not auth.lower().startswith('bearer '):
        return await call_next(request)
    token = auth[7:].strip()

    try:
        from app.core.security import decode_access_token
        payload = decode_access_token(token)
        uid = payload.get('sub') if payload else None
    except Exception:
        return await call_next(request)
    if not uid:
        return await call_next(request)

    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text
        async with AsyncSessionLocal() as _db:
            row = (await _db.execute(_text(
                "SELECT is_subaccount FROM users WHERE user_id = CAST(:u AS UUID)"
            ), {'u': uid})).first()
        if row and row[0]:
            return JSONResponse(status_code=403, content={
                'detail': '子账号仅支持查看，无任何写操作权限',
                'code': 'subaccount_readonly',
            })
    except Exception:
        pass
    return await call_next(request)


@app.middleware("http")
async def maintenance_guard(request: Request, call_next):
    """Block mutating trading/strategy requests while maintenance is on.
    Allow-list: GET/HEAD/OPTIONS + auth + site-status + maintenance endpoints +
    admin toggle itself so operator can disable. Everything else POST/PUT/DELETE
    returns 503."""
    method = request.method.upper()
    path = request.url.path
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return await call_next(request)
    ALLOW_PREFIX = (
        '/api/v1/auth/',
        '/api/v1/users/me',
        '/api/v1/site-status',
        '/api/v1/announcements',
        '/api/v1/maintenance',
        '/api/v1/agent/openclaw-toggle',
        '/api/v1/agent/kill',
        '/ws',
    )
    if any(path.startswith(x) for x in ALLOW_PREFIX):
        return await call_next(request)
    try:
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import text as _text
        async with AsyncSessionLocal() as _db:
            row = (await _db.execute(_text(
                "SELECT is_active, reason, scheduled_resume_at FROM system_maintenance_state WHERE id=1"
            ))).first()
        if row and row[0]:
            resume = row[2].isoformat() if row[2] else None
            return JSONResponse(status_code=503, content={
                'detail': f'系统维护中' + (f'：{row[1]}' if row[1] else ''),
                'code': 'maintenance',
                'reason': row[1],
                'scheduled_resume_at': resume,
            })
    except Exception:
        pass
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.debug(f"[REQUEST] {request.method} {request.url.path}")
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

    logger.debug(f"[RESPONSE] {request.method} {request.url.path} - Status: {response.status_code}")
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
from app.api.v1 import manual_ledger as _mledger
app.include_router(_mledger.router, prefix="/api/v1/manual-ledger", tags=["ManualLedger"])
from app.api.v1 import ai_arb_analysis as _aiarb
app.include_router(_aiarb.router, prefix="/api/v1/ai-arb", tags=["AIArbAnalysis"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["Accounts"])
app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["Strategies"])
app.include_router(market.router, prefix="/api/v1/market", tags=["Market Data"])
app.include_router(risk.router, prefix="/api/v1/risk", tags=["Risk Control"])
app.include_router(automation.router, prefix="/api/v1/automation", tags=["Automation"])
app.include_router(strategy_processes.router, prefix="/api/v1/automation", tags=["StrategyProcesses"])
app.include_router(trading.router, prefix="/api/v1/trading", tags=["Trading"])
app.include_router(pnl.router, prefix="/api/v1/pnl", tags=["PnL Analytics"])
app.include_router(hedging.router, prefix="/api/v1/hedging", tags=["Hedging Platform Management"])
app.include_router(pair_accounts.router, prefix="/api/v1", tags=["产品对账户绑定"])
app.include_router(hedge_ratio.router, prefix="/api/v1", tags=["对冲倍数"])
app.include_router(hedge_records.router, tags=["对冲下单记录"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(test.router, prefix="/api/v1/test", tags=["Test"])
app.include_router(rbac.router, prefix="/api/v1/rbac", tags=["RBAC权限管理"])
app.include_router(security_components.router, prefix="/api/v1/security", tags=["安全组件管理"])
app.include_router(ssl_certificates.router, prefix="/api/v1/ssl", tags=["SSL证书管理"])
app.include_router(system_monitor.router, prefix="/api/v1/monitor", tags=["系统监控"])
app.include_router(key_management.router, prefix="/api/v1/keys", tags=["密钥管理"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["OpenCLAW Agent"])
app.include_router(aicoin.router, prefix="/api/v1/aicoin", tags=["AiCoin K-line"])
app.include_router(site_status.router, prefix="/api/v1", tags=["Site Status"])
from app.api.v1 import subaccount
app.include_router(subaccount.router, prefix="/api/v1", tags=["Sub-account"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["通知服务"])
app.include_router(sound_files.router, prefix="/api/v1", tags=["声音文件管理"])
app.include_router(timing_configs.router, prefix="/api/v1", tags=["时间配置管理"])
app.include_router(arbitrage_opportunities.router, prefix="/api/v1", tags=["套利机会"])
app.include_router(proxies.router, prefix="/api/v1", tags=["代理管理"])
app.include_router(mt5_clients.router, prefix="/api/v1", tags=["MT5客户端管理"])
app.include_router(mt5_instances.router, prefix="/api/v1", tags=["MT5实例管理"])
app.include_router(mt5_infra.router, prefix="/api/v1/mt5-infra", tags=["MT5基础设施"])
app.include_router(mt5_server.router, prefix="/api/v1", tags=["MT5服务器状态"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(dashboard_viz.router, prefix="/api/v1/accounts", tags=["Dashboard可视化"])

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


# ── Slippage auto-resume worker (Level 1 pauses → 10min auto-clear if no interaction) ──
@app.on_event("startup")
async def _start_slippage_auto_resume_worker():
    import asyncio as _aio_slip
    from app.services.slippage_guard import auto_resume_tick as _slip_tick

    async def _worker():
        import logging as _lg
        _lg.getLogger(__name__).info("[SLIPPAGE_GUARD] auto-resume worker started")
        while True:
            try:
                await _slip_tick()
            except Exception as _e:
                _lg.getLogger(__name__).error(f"[SLIPPAGE_GUARD] worker error: {_e}")
            await _aio_slip.sleep(30)

    _aio_slip.create_task(_worker())
