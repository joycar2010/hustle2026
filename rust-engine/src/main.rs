mod config;
mod tick_store;
mod db;
mod exchange;
mod http;
mod ws;
mod redis_bridge;
mod mt5_bridge;

use config::AppConfig;
use db::pairs::{self, PairConfig};
use mt5_bridge::Mt5Bridge;
use tick_store::TickStore;
use ws::hub::Hub;
use ws::handler::{WsState, ws_handler};

use axum::{routing::get, Router};
use std::sync::Arc;
use tower_http::cors::{CorsLayer, Any};
use tracing::info;

pub struct AppState {
    pub tick_store: Arc<TickStore>,
    pub pairs: Vec<PairConfig>,
    pub hub: Arc<Hub>,
    pub mt5_bridge: Mt5Bridge,
    pub config: AppConfig,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "cex_engine=info".into()),
        )
        .init();

    let cfg = AppConfig::from_env();
    info!("cex-engine v0.2.0 starting, listen={}", cfg.listen_addr);

    // 1. Database — load pair configs
    let pg_cfg: deadpool_postgres::Config = {
        let mut c = deadpool_postgres::Config::new();
        c.url = Some(cfg.database_url.clone());
        c
    };
    let pool = pg_cfg
        .create_pool(Some(deadpool_postgres::Runtime::Tokio1), tokio_postgres::NoTls)
        .expect("Failed to create PG pool");
    let pair_configs = pairs::load_pairs(&pool).await;

    // 2. Tick store
    let tick_store = Arc::new(TickStore::new());

    // 3. WebSocket Hub
    let hub = Hub::new();

    // 4. MT5 Bridge client
    let mt5 = Mt5Bridge::new(cfg.mt5_api_key.clone());

    // 5. Spawn exchange WS clients
    let binance_symbols = pairs::symbols_by_platform(&pair_configs, 1);
    if !binance_symbols.is_empty() {
        let url = pairs::build_binance_streams_url(&binance_symbols);
        info!("[Startup] Binance WS: {} symbols", binance_symbols.len());
        tokio::spawn(exchange::binance::run(url, tick_store.clone()));
    }

    let okx_symbols = pairs::symbols_by_platform(&pair_configs, 5);
    if !okx_symbols.is_empty() {
        info!("[Startup] OKX WS: {} symbols", okx_symbols.len());
        tokio::spawn(exchange::okx::run(okx_symbols, tick_store.clone()));
    }

    let gate_symbols = pairs::symbols_by_platform(&pair_configs, 4);
    if !gate_symbols.is_empty() {
        info!("[Startup] Gate WS: {} symbols", gate_symbols.len());
        tokio::spawn(exchange::gate::run(gate_symbols, tick_store.clone()));
    }

    let bitget_symbols = pairs::symbols_by_platform(&pair_configs, 6);
    if !bitget_symbols.is_empty() {
        info!("[Startup] Bitget WS: {} symbols", bitget_symbols.len());
        tokio::spawn(exchange::bitget::run(bitget_symbols, tick_store.clone()));
    }

    // 6. Spawn Redis bridge
    tokio::spawn(redis_bridge::run(cfg.redis_url.clone(), hub.clone()));

    // 7. Build axum app
    let app_state = Arc::new(AppState {
        tick_store,
        pairs: pair_configs,
        hub: hub.clone(),
        mt5_bridge: mt5,
        config: cfg.clone(),
    });

    let ws_state = Arc::new(WsState {
        hub: hub.clone(),
        config: cfg.clone(),
    });

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = http::router(app_state)
        .route("/api/v1/ws", get(ws_handler).with_state(ws_state.clone()))
        .route("/api/v1/ws/stats", get({
            let h = hub.clone();
            move || async move {
                axum::Json(serde_json::json!({
                    "connections": { "total": h.client_count() },
                    "service": "rust-engine",
                    "timestamp": std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64,
                }))
            }
        }))
        .layer(cors);

    info!("cex-engine listening on {}", cfg.listen_addr);
    let listener = tokio::net::TcpListener::bind(&cfg.listen_addr)
        .await
        .expect("Failed to bind");
    axum::serve(listener, app).await.expect("Server error");
}
