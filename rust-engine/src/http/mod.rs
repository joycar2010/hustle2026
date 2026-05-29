pub mod health;
pub mod spread;
pub mod quote;
pub mod orderbook;
pub mod funding_rate;
pub mod swap_rate;

use axum::{Router, routing::get};
use std::sync::Arc;

pub fn router(state: Arc<crate::AppState>) -> Router {
    Router::new()
        .route("/api/v1/health", get(health::handler))
        .route("/api/v1/market/spread", get(spread::handler))
        .route("/api/v1/market/binance/quote", get(quote::handler))
        .route("/api/v1/market/orderbook", get(orderbook::handler))
        .route("/api/v1/market/funding-rate", get(funding_rate::handler))
        .route("/api/v1/market/bybit-swap-rate", get(swap_rate::handler))
        .with_state(state)
}
