mod config;
mod redis_pub;
mod spread;
mod types;
mod ws;

use crate::config::AppConfig;
use crate::redis_pub::RedisPublisher;
use crate::spread::calculator;
use crate::types::{LatencyStats, TickerData};
use dashmap::DashMap;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{mpsc, Mutex};
use tracing::{info, warn};

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("cex_engine=info".parse().unwrap()),
        )
        .init();

    info!("CEX Engine starting...");

    let cfg = AppConfig::load();
    info!(symbols = cfg.symbols.len(), redis = %cfg.redis_url, "Config loaded");

    let publisher = RedisPublisher::new(&cfg.redis_url)
        .await
        .expect("Failed to connect to Redis");
    let publisher = Arc::new(publisher);

    // DashMap: symbol -> (spot_ticker, futures_ticker)
    let tickers: Arc<DashMap<String, (TickerData, TickerData)>> = Arc::new(DashMap::new());

    let (update_tx, update_rx) = mpsc::unbounded_channel::<String>();

    // Spawn spot WS
    let spot_tickers = tickers.clone();
    let spot_symbols = cfg.symbols.clone();
    let spot_tx = update_tx.clone();
    tokio::spawn(async move {
        ws::binance_spot::run(spot_symbols, spot_tickers, spot_tx).await;
    });

    // Spawn futures WS
    let fut_tickers = tickers.clone();
    let fut_symbols = cfg.symbols.clone();
    let fut_tx = update_tx.clone();
    tokio::spawn(async move {
        ws::binance_futures::run(fut_symbols, fut_tickers, fut_tx).await;
    });

    drop(update_tx);

    // Spawn latency reporter
    let stats = Arc::new(Mutex::new(LatencyStats::new()));
    let stats_reporter = stats.clone();
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(60));
        loop {
            interval.tick().await;
            let mut s = stats_reporter.lock().await;
            let (avg, p99, max) = s.report_and_reset();
            if avg > 0.0 {
                info!(
                    avg_us = format!("{:.0}", avg),
                    p99_us = p99,
                    max_us = max,
                    "Spread pipeline latency"
                );
            }
        }
    });

    // Main loop: process ticker updates and calculate spreads
    process_updates(update_rx, tickers, publisher, stats).await;
}

async fn process_updates(
    mut update_rx: mpsc::UnboundedReceiver<String>,
    tickers: Arc<DashMap<String, (TickerData, TickerData)>>,
    publisher: Arc<RedisPublisher>,
    stats: Arc<Mutex<LatencyStats>>,
) {
    info!("Spread processor started, waiting for ticker updates...");

    let mut update_count: u64 = 0;
    let mut last_log = Instant::now();

    while let Some(symbol) = update_rx.recv().await {
        let start = Instant::now();

        if let Some(pair) = tickers.get(&symbol) {
            let (spot, futures) = pair.value();
            if let Some(snapshot) = calculator::calculate(&symbol, spot, futures) {
                publisher.publish_spread(&snapshot).await;

                let elapsed_us = start.elapsed().as_micros() as u64;
                let mut s = stats.lock().await;
                s.record(elapsed_us);
            }
        }

        update_count += 1;
        if last_log.elapsed().as_secs() >= 30 {
            let active = tickers
                .iter()
                .filter(|e| {
                    let (s, f) = e.value();
                    s.ts > 0 && f.ts > 0
                })
                .count();
            info!(
                updates_30s = update_count,
                active_pairs = active,
                "Throughput"
            );
            update_count = 0;
            last_log = Instant::now();
        }
    }

    warn!("Update channel closed, shutting down");
}
