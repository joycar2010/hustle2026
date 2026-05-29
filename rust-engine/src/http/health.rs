use axum::{extract::State, Json};
use std::sync::Arc;

pub async fn handler(State(state): State<Arc<crate::AppState>>) -> Json<serde_json::Value> {
    let tick_count = state.tick_store.tick_count();
    let ws_clients = state.hub.client_count();
    let status = if tick_count > 0 { "ok" } else { "degraded" };
    let pair_codes: Vec<String> = state.pairs.iter().map(|p| p.pair_code.clone()).collect();
    Json(serde_json::json!({
        "status": status,
        "service": "rust-engine",
        "ws_clients": ws_clients,
        "tick_count": tick_count,
        "server_time": now_ms(),
        "pairs": pair_codes,
    }))
}

fn now_ms() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64
}
