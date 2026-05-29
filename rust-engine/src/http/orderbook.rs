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

    let binance = fetch_binance_book(&pair.a_symbol).await;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64;
    Json(serde_json::json!({
        "pair_code": pc,
        "binance": binance.unwrap_or_default(),
        "timestamp": now,
    }))
}

async fn fetch_binance_book(symbol: &str) -> Option<serde_json::Value> {
    let url = format!(
        "https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={}",
        symbol
    );
    let resp: serde_json::Value = reqwest::get(&url).await.ok()?.json().await.ok()?;
    let bid_price = resp.get("bidPrice")?.as_str()?.parse::<f64>().ok()?;
    let ask_price = resp.get("askPrice")?.as_str()?.parse::<f64>().ok()?;
    let bid_qty = resp.get("bidQty")?.as_str()?.parse::<f64>().ok()?;
    let ask_qty = resp.get("askQty")?.as_str()?.parse::<f64>().ok()?;
    Some(serde_json::json!({
        "symbol": symbol,
        "bid_price": bid_price,
        "bid_volume": bid_qty,
        "ask_price": ask_price,
        "ask_volume": ask_qty,
        "timestamp": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64,
    }))
}
