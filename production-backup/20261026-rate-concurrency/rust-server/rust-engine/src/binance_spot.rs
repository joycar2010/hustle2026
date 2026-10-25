use crate::config::load_universe_symbols;
use crate::types::{BinanceCombinedStream, TickerData};
use dashmap::DashMap;
use futures_util::StreamExt;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

/// half-open 看门狗: 超过此秒数未收任何帧 → 视为 TCP 半开假死 → 返回 Err 触发重连。
const WS_IDLE_TIMEOUT_SECS: u64 = 30;

pub async fn run(
    initial_symbols: Vec<String>,
    redis_url: String,
    tickers: Arc<DashMap<String, (TickerData, TickerData)>>,
    update_tx: mpsc::UnboundedSender<String>,
) {
    let mut symbols = initial_symbols;
    loop {
        if let Err(e) = connect_and_stream(&symbols, &tickers, &update_tx).await {
            error!(error = %e, "Spot WS disconnected");
        }
        warn!("Spot WS reconnecting in 2s...");
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        // 每次重连时重读 engine:universe,自动订阅新推送的币
        let fresh = load_universe_symbols(&redis_url).await;
        if !fresh.is_empty() && fresh != symbols {
            info!(prev = symbols.len(), next = fresh.len(), "Spot WS universe updated on reconnect");
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
            "wss://stream.binance.com:9443/stream?streams={}",
            stream_param
        );
        let num_streams = chunk.len();

        let tickers = tickers.clone();
        let update_tx = update_tx.clone();

        let handle = tokio::spawn(async move {
            let (ws, _) = tokio_tungstenite::connect_async(&url).await?;
            info!(streams = num_streams, "Spot WS connected");

            let (_, mut read) = ws.split();
            let idle = std::time::Duration::from_secs(WS_IDLE_TIMEOUT_SECS);

            loop {
                // half-open 看门狗: 超时未收帧 → Err → chunk task 结束 → try_join_all 短路 → 整体重连
                match tokio::time::timeout(idle, read.next()).await {
                    Err(_elapsed) => {
                        warn!(
                            streams = num_streams,
                            timeout_s = WS_IDLE_TIMEOUT_SECS,
                            "Spot WS idle timeout — half-open detected, triggering reconnect"
                        );
                        return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                            "idle timeout".into()
                        );
                    }
                    Ok(None) => break, // stream 正常关闭
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

                                let spot = TickerData {
                                    bid: combined.data.bid_price,
                                    ask: combined.data.ask_price,
                                    ts,
                                };

                                tickers
                                    .entry(symbol.clone())
                                    .and_modify(|pair| pair.0 = spot.clone())
                                    .or_insert_with(|| (spot, TickerData::default()));

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

    // try_join_all: 任一 chunk 出错立即返回 Err → 外层 loop 2s 后整体重连。
    // 修复原因: 原 `for h in handles { h.await? }` 顺序等待,某 chunk TCP 半开永久阻塞则整体卡死。
    let results: Result<Vec<_>, _> = futures_util::future::try_join_all(handles).await;
    if let Err(e) = results {
        return Err(format!("Spot WS chunk join error: {}", e).into());
    }
    Ok(())
}
