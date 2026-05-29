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

    if pair.bridge_url.is_empty() {
        return Json(serde_json::json!({"error": format!("No bridge URL for {pc}")}));
    }

    let info = match state.mt5_bridge.get_symbol_info(&pair.bridge_url, &pair.mt5_symbol).await {
        Some(v) => v,
        None => return Json(serde_json::json!({"error": "MT5 bridge unreachable"})),
    };

    let swap_long = info.get("swap_long").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let swap_short = info.get("swap_short").and_then(|v| v.as_f64()).unwrap_or(0.0);

    Json(serde_json::json!({
        "symbol": pair.mt5_symbol,
        "pair_code": pc,
        "long_swap_per_lot": swap_long / pair.conversion_factor,
        "short_swap_per_lot": swap_short / pair.conversion_factor,
        "swap_mode": info.get("swap_mode").and_then(|v| v.as_i64()).unwrap_or(0),
        "rollover_day": info.get("swap_rollover3days").and_then(|v| v.as_i64()).unwrap_or(0),
        "contract_size": info.get("trade_contract_size").and_then(|v| v.as_f64()).unwrap_or(0.0),
        "timestamp": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64,
    }))
}
