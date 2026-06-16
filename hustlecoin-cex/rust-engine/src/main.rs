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
use rust_decimal::Decimal;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};
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

    let cfg = AppConfig::load().await;
    info!(symbols = cfg.symbols.len(), redis = %cfg.redis_url, "Config loaded");

    let publisher = RedisPublisher::new(&cfg.redis_url)
        .await
        .expect("Failed to connect to Redis");
    let publisher = Arc::new(publisher);

    // DashMap: symbol -> (spot_ticker, futures_ticker)
    let tickers: Arc<DashMap<String, (TickerData, TickerData)>> = Arc::new(DashMap::new());

    let (update_tx, update_rx) = mpsc::unbounded_channel::<String>();

    // Spawn spot WS(订阅交易宇宙 <symbol>@bookTicker,200/连接分块)
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
    process_updates(
        update_rx,
        tickers,
        publisher,
        stats,
        cfg.max_staleness_ms,
        cfg.max_spread_pct,
        cfg.frozen_ms,
    )
    .await;
}

async fn process_updates(
    mut update_rx: mpsc::UnboundedReceiver<String>,
    tickers: Arc<DashMap<String, (TickerData, TickerData)>>,
    publisher: Arc<RedisPublisher>,
    stats: Arc<Mutex<LatencyStats>>,
    max_staleness_ms: i64,
    max_spread_pct: Decimal,
    frozen_ms: i64,
) {
    info!(
        max_staleness_ms,
        max_spread_pct = %max_spread_pct,
        frozen_ms,
        "Spread processor started, waiting for ticker updates..."
    );

    let mut update_count: u64 = 0;
    let mut publish_count: u64 = 0;
    let mut stale_skipped: u64 = 0;
    let mut divergent_skipped: u64 = 0;
    let mut frozen_skipped: u64 = 0;
    // 冻结护栏状态: symbol -> (spot_bid, spot_ask, spot价最后变动ms, fut_bid, fut_ask, fut价最后变动ms)
    let mut px_state: HashMap<String, (Decimal, Decimal, i64, Decimal, Decimal, i64)> = HashMap::new();
    let mut last_log = Instant::now();

    while let Some(symbol) = update_rx.recv().await {
        let start = Instant::now();

        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as i64;

        let mut stale = false;
        let mut frozen = false;
        let snapshot = tickers.get(&symbol).and_then(|pair| {
            let (spot, futures) = pair.value();
            // 新鲜度护栏: 任一腿超过阈值未更新 → 不发布(live腿×stale腿=假点差,真因)。
            // spot 无事件时间用本地 now() 戳;futures 用币安 T(事件时间)。任一冻结即此处拦下。
            if now_ms - spot.ts > max_staleness_ms || now_ms - futures.ts > max_staleness_ms {
                stale = true;
                return None;
            }
            // 冻结护栏: bookTicker 在「数量」变化时也推送(价不变也刷新 ts),ts 护栏漏。
            // 某腿买一/卖一价连续 frozen_ms 未变 → 视为价格冻结(停牌/退市挂单未撤),
            // 与活腿相乘会产生假基差 → 不发布。活跃币价毫秒级跳动,此处永不触发。
            let st = px_state.entry(symbol.clone()).or_insert((
                spot.bid, spot.ask, now_ms, futures.bid, futures.ask, now_ms,
            ));
            if spot.bid != st.0 || spot.ask != st.1 {
                st.0 = spot.bid; st.1 = spot.ask; st.2 = now_ms;
            }
            if futures.bid != st.3 || futures.ask != st.4 {
                st.3 = futures.bid; st.4 = futures.ask; st.5 = now_ms;
            }
            if now_ms - st.2 > frozen_ms || now_ms - st.5 > frozen_ms {
                frozen = true;
                return None;
            }
            calculator::calculate(&symbol, spot, futures)
        });

        if stale {
            stale_skipped += 1;
        }
        if frozen {
            frozen_skipped += 1;
        }

        if let Some(snapshot) = snapshot {
            // 兜底护栏: 点差幅度异常(冻结盘口/熔断/下架合约)→ 不发布坏数据
            if snapshot.spread_short.abs() > max_spread_pct
                || snapshot.spread_long.abs() > max_spread_pct
            {
                divergent_skipped += 1;
            } else {
                publisher.publish_spread(&snapshot).await;
                publish_count += 1;

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
                publishes_30s = publish_count,
                stale_skipped_30s = stale_skipped,
                frozen_skipped_30s = frozen_skipped,
                divergent_skipped_30s = divergent_skipped,
                active_pairs = active,
                "Throughput"
            );
            // 写 Redis 供 python 巡检读取(engine:throughput)
            let tput = format!(
                "{{\"updates\":{},\"publishes\":{},\"stale_skipped\":{},\"frozen_skipped\":{},\"divergent_skipped\":{},\"active_pairs\":{},\"window_s\":30,\"ts\":{}}}",
                update_count, publish_count, stale_skipped, frozen_skipped, divergent_skipped, active, now_ms
            );
            publisher.set_throughput(&tput).await;
            update_count = 0;
            publish_count = 0;
            stale_skipped = 0;
            frozen_skipped = 0;
            divergent_skipped = 0;
            last_log = Instant::now();
        }
    }

    warn!("Update channel closed, shutting down");
}
