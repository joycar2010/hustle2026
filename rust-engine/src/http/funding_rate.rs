use axum::{extract::{Query, State}, Json};
use serde::Deserialize;
use std::sync::Arc;

#[derive(Deserialize)]
pub struct Params {
    pair_code: Option<String>,
    pair: Option<String>,
}

#[derive(Deserialize)]
struct BinancePremium {
    symbol: String,
    #[serde(rename = "markPrice")]
    mark_price: String,
    #[serde(rename = "lastFundingRate")]
    last_funding_rate: String,
    #[serde(rename = "nextFundingTime")]
    next_funding_time: i64,
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

    let url = format!(
        "https://fapi.binance.com/fapi/v1/premiumIndex?symbol={}",
        pair.a_symbol
    );
    let resp: BinancePremium = match reqwest::get(&url).await.and_then(|r| Ok(r)).ok() {
        Some(r) => match r.json().await {
            Ok(v) => v,
            Err(e) => return Json(serde_json::json!({"error": e.to_string()})),
        },
        None => return Json(serde_json::json!({"error": "Binance API unreachable"})),
    };

    let mark_price: f64 = resp.mark_price.parse().unwrap_or(0.0);
    let rate: f64 = resp.last_funding_rate.parse().unwrap_or(0.0);
    let per_lot = pair.conversion_factor * mark_price * rate;

    Json(serde_json::json!({
        "symbol": resp.symbol,
        "pair_code": pc,
        "mark_price": mark_price,
        "funding_rate": rate,
        "funding_rate_pct": rate * 100.0,
        "long_cost_per_lot": per_lot,
        "short_cost_per_lot": -per_lot,
        "next_funding_time": resp.next_funding_time,
        "timestamp": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as i64,
    }))
}
