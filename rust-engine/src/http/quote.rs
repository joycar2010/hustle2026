use axum::{extract::{Query, State}, Json};
use serde::Deserialize;
use std::sync::Arc;

#[derive(Deserialize)]
pub struct Params {
    pair_code: Option<String>,
    pair: Option<String>,
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
    match state.tick_store.get(pair.a_platform_id as u32, &pair.a_symbol) {
        Some(t) => Json(serde_json::json!({
            "symbol": pair.a_symbol,
            "pair_code": pc,
            "bid": t.bid,
            "ask": t.ask,
            "spread": t.ask - t.bid,
            "timestamp": t.timestamp,
        })),
        None => Json(serde_json::json!({"error": format!("No data for {}", pair.a_symbol)})),
    }
}
