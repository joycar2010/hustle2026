use crate::config::load_universe_symbols;
use crate::types::{BinanceCombinedStream, TickerData};
use dashmap::DashMap;
use futures_util::StreamExt;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

const WS_IDLE_TIMEOUT_SECS: u64 = 30;

/// 逐币(per-stream)新鲜度看门狗: 见 binance_spot.rs 同款说明(阈值按实测稳态校准)。合约腿 = tickers 的 .1。
const FRESH_CHECK_SECS: u64 = 20;
const SYMBOL_STALE_SECS: i64 = 600;
const CHUNK_STALE_FRACTION: f64 = 0.4;
const FRESH_GRACE_SECS: u64 = 75;

pub async fn run(
    initial_symbols: Vec<String>,
    redis_url: String,
    tickers: Arc<DashMap<String, (TickerData, TickerData)>>,
    update_tx: mpsc::UnboundedSender<String>,
) {
    let mut symbols = initial_symbols;
    loop {
        if let Err(e) = connect_and_stream(&symbols, &tickers, &update_tx).await {
            error!(error = %e, "Futures WS disconnected");
        }
        warn!("Futures WS reconnecting in 2s...");
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        let fresh = load_universe_symbols(&redis_url).await;
        if !fresh.is_empty() && fresh != symbols {
            info!(prev = symbols.len(), next = fresh.len(), "Futures WS universe updated on reconnect");
            symbols = fresh;
        }
    }
}

async fn connect_and_stream(
    symbols: &[String],
    tickers: &Arc<DashMap<String, (TickerData, TickerData)>>,
    update_tx: &mpsc::UnboundedSender<String>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let streams: Vec<String> = symbols.iter().map(|s| format!("{}@bookTicker", s)).collect();

    let owned_chunks: Vec<Vec<String>> = streams
        .chunks(200)
        .map(|c| c.to_vec())
        .collect();

    let mut handles = Vec::new();

    for chunk in owned_chunks {
        let stream_param = chunk.join("/");
        let url = format!(
            "wss://fstream.binance.com/stream?streams={}",
            stream_param
        );
        let num_streams = chunk.len();

        let tickers = tickers.clone();
        let update_tx = update_tx.clone();

        let handle = tokio::spawn(async move {
            let (ws, _) = tokio_tungstenite::connect_async(&url).await?;
            info!(streams = num_streams, "Futures WS connected");

            let (_, mut read) = ws.split();
            let idle = std::time::Duration::from_secs(WS_IDLE_TIMEOUT_SECS);

            loop {
                match tokio::time::timeout(idle, read.next()).await {
                    Err(_elapsed) => {
                        warn!(
                            streams = num_streams,
                            timeout_s = WS_IDLE_TIMEOUT_SECS,
                            "Futures WS idle timeout — half-open detected, triggering reconnect"
                        );
                        return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                            "idle timeout".into()
                        );
                    }
                    Ok(None) => break,
                    Ok(Some(msg)) => {
                        let msg = msg?;
                        if let tokio_tungstenite::tungstenite::Message::Text(text) = msg {
                            if let Ok(combined) = serde_json::from_str::<BinanceCombinedStream>(&text) {
                                let symbol = combined.data.symbol.clone();
                                let ts = combined.data.timestamp.unwrap_or_else(|| {
                                    std::time::SystemTime::now()
                                        .duration_since(std::time::UNIX_EPOCH)
                                        .unwrap()
                                        .as_millis() as i64
                                });

                                let fut = TickerData {
                                    bid: combined.data.bid_price,
                                    ask: combined.data.ask_price,
                                    ts,
                                };

                                tickers
                                    .entry(symbol.clone())
                                    .and_modify(|pair| pair.1 = fut.clone())
                                    .or_insert_with(|| (TickerData::default(), fut));

                                let _ = update_tx.send(symbol);
                            }
                        }
                    }
                }
            }

            Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
        });
        handles.push(handle);
    }

    // 逐币新鲜度看门狗(per-stream): 合约腿 = tickers 的 .1。某 200-分片整段静默即强制重连。
    {
        let mon_symbols: Vec<String> = symbols.to_vec();
        let mon_tickers = tickers.clone();
        let monitor = tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_secs(FRESH_GRACE_SECS)).await;
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(FRESH_CHECK_SECS)).await;
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_millis() as i64;
                for chunk in mon_symbols.chunks(200) {
                    if chunk.is_empty() {
                        continue;
                    }
                    let stale = chunk
                        .iter()
                        .filter(|s| {
                            let last = mon_tickers.get(s.as_str()).map(|t| t.1.ts).unwrap_or(0);
                            now - last > SYMBOL_STALE_SECS * 1000
                        })
                        .count();
                    if (stale as f64 / chunk.len() as f64) >= CHUNK_STALE_FRACTION {
                        warn!(
                            stale,
                            total = chunk.len(),
                            "Futures per-symbol freshness: chunk mostly stale — forcing reconnect"
                        );
                        return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                            "futures chunk stale".into(),
                        );
                    }
                }
            }
        });
        handles.push(monitor);
    }

    // try_join_all: 任一 chunk 出错立即返回 Err → 外层 loop 2s 后整体重连
    let results: Result<Vec<_>, _> = futures_util::future::try_join_all(handles).await;
    if let Err(e) = results {
        return Err(format!("Futures WS chunk join error: {}", e).into());
    }
    Ok(())
}
