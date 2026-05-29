use axum::{extract::{Query, State}, Json};
use serde::Deserialize;
use std::sync::Arc;

#[derive(Deserialize)]
pub struct Params {
    pair_code: Option<String>,
    pair: Option<String>,
    binance_symbol: Option<String>,
    bybit_symbol: Option<String>,
}

pub async fn handler(
    Query(p): Query<Params>,
    State(state): State<Arc<crate::AppState>>,
) -> Json<serde_json::Value> {
    let pc = p.pair_code.or(p.pair).unwrap_or_else(|| "XAU".into());
    let pair = match state.pairs.iter().find(|x| x.pair_code == pc) {
        Some(p) => p,
        None => return Json(serde_json::json!({"error": format!("Unknown pair_code: {pc}")})),
    };

    let a_tick = match state.tick_store.get(pair.a_platform_id as u32, &pair.a_symbol) {
        Some(t) => t,
        None => return Json(serde_json::json!({"error": format!("No A-side data for {}", pair.a_symbol)})),
    };

    let b_tick = match state.mt5_bridge.get_tick(&pair.bridge_url, &pair.mt5_symbol).await {
        Some((bid, ask)) => (bid, ask),
        None => return Json(serde_json::json!({"error": format!("MT5 bridge failed for {}", pair.mt5_symbol)})),
    };

    let now = now_ms();
    Json(serde_json::json!({
        "pair_code": pc,
        "a_quote": {
            "symbol": pair.a_symbol,
            "bid_price": a_tick.bid,
            "ask_price": a_tick.ask,
            "timestamp": a_tick.timestamp,
        },
        "b_quote": {
            "symbol": pair.mt5_symbol,
            "bid_price": b_tick.0,
            "ask_price": b_tick.1,
            "timestamp": now,
        },
        "forward_entry_spread": b_tick.0 - a_tick.bid,
        "forward_exit_spread": b_tick.1 - a_tick.ask,
        "reverse_entry_spread": a_tick.ask - b_tick.1,
        "reverse_exit_spread": a_tick.bid - b_tick.0,
        "timestamp": now,
    }))
}

fn now_ms() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64
}
