//! dcm-feed:多所行情 feed(DexCexMix 数据面)。
//! fork 自 coin cex-engine 的加固骨架,venue 泛型化 + 键升维 (venue,market,symbol)。
//! 数据面只采集归一不判断:不算点差、不做经济护栏;发布原始归一化 L1 + 双时间戳,
//! 新鲜度/冻结判定由下游消费者按各自口径做。仅保留 bid/ask>0 的坏帧过滤。

mod config;
mod redis_pub;
mod types;
mod ws;

use crate::config::AppConfig;
use crate::redis_pub::RedisPublisher;
use crate::types::TickerSnapshot;
use crate::ws::venues::ALL_SPECS;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::mpsc;
use tracing::{info, warn};

#[tokio::main]
async fn main() {
    // rustls 0.23 要求进程级唯一 CryptoProvider;不显式 install 则首个 TLS 握手 panic
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("install rustls ring provider");

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("dcm_feed=info".parse().unwrap()),
        )
        .init();

    info!("dcm-feed starting...");
    let cfg = AppConfig::load();

    let publisher = Arc::new(
        RedisPublisher::new(&cfg.redis_url)
            .await
            .expect("Failed to connect to Redis"),
    );

    let tickers: ws::TickerMap = Arc::new(dashmap::DashMap::new());
    let (update_tx, update_rx) = mpsc::unbounded_channel::<String>();

    let mut started = 0usize;
    for spec in ALL_SPECS {
        if !cfg.enabled.iter().any(|e| e == &spec.key()) {
            continue;
        }
        let symbols = {
            let v = config::load_universe(&cfg.redis_url, spec.venue, spec.market).await;
            if v.is_empty() {
                warn!(feed = %spec.key(), "universe missing in Redis — using fallback majors");
                config::fallback_bases().iter().map(|b| (spec.to_native)(b)).collect()
            } else {
                v
            }
        };
        info!(feed = %spec.key(), symbols = symbols.len(), "starting feed");
        let spec = *spec;
        let tickers = tickers.clone();
        let update_tx = update_tx.clone();
        let redis_url = cfg.redis_url.clone();
        tokio::spawn(async move {
            ws::run(spec, symbols, redis_url, tickers, update_tx).await;
        });
        started += 1;
    }
    drop(update_tx);
    assert!(started > 0, "no feed enabled — check DCM_FEED_VENUES");
    info!(feeds = started, redis = %cfg.redis_url, "all feeds spawned");

    process_updates(update_rx, tickers, publisher, cfg.enabled).await;
}

/// 主循环:收 (venue:market:SYMBOL) 更新 → 坏帧过滤 → 发布快照;30s 吞吐计数即心跳。
async fn process_updates(
    mut update_rx: mpsc::UnboundedReceiver<String>,
    tickers: ws::TickerMap,
    publisher: Arc<RedisPublisher>,
    enabled: Vec<String>,
) {
    let mut update_count: u64 = 0;
    let mut publish_count: u64 = 0;
    let mut bad_skipped: u64 = 0;
    let mut last_log = Instant::now();

    while let Some(key) = update_rx.recv().await {
        let Some(td) = tickers.get(&key).map(|e| e.value().clone()) else {
            continue;
        };
        update_count += 1;

        // 唯一的进程内过滤:零价/负价坏帧(下架合约 emit 0 价等)不发布
        if td.bid <= rust_decimal::Decimal::ZERO || td.ask <= rust_decimal::Decimal::ZERO {
            bad_skipped += 1;
        } else {
            let mut parts = key.splitn(3, ':');
            let (Some(venue), Some(market), Some(symbol)) =
                (parts.next(), parts.next(), parts.next())
            else {
                continue;
            };
            let snap = TickerSnapshot {
                venue,
                market,
                symbol,
                bid: td.bid,
                ask: td.ask,
                bid_sz: td.bid_sz,
                ask_sz: td.ask_sz,
                ts: td.ts,
                recv_ts: td.recv_ts,
            };
            publisher.publish_ticker(&snap).await;
            publish_count += 1;
        }

        if last_log.elapsed().as_secs() >= 30 {
            let now_ms = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_millis() as i64;
            let active = tickers
                .iter()
                .filter(|e| now_ms - e.value().recv_ts < 60_000)
                .count();
            info!(
                updates_30s = update_count,
                publishes_30s = publish_count,
                bad_skipped_30s = bad_skipped,
                active_streams = active,
                "Throughput"
            );
            let hb = format!(
                "{{\"service\":\"feed-cex\",\"ts\":{},\"pid\":{},\"updates\":{},\"publishes\":{},\"bad_skipped\":{},\"active_streams\":{},\"window_s\":30,\"feeds\":{:?}}}",
                now_ms / 1000,
                std::process::id(),
                update_count, publish_count, bad_skipped, active, enabled
            );
            publisher.set_heartbeat(&hb).await;
            update_count = 0;
            publish_count = 0;
            bad_skipped = 0;
            last_log = Instant::now();
        }
    }
    warn!("update channel closed, shutting down");
}
