use crate::config::load_universe_symbols_checked;
use crate::types::{BinanceCombinedStream, TickerData};
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::sync::mpsc;
use tokio::task::JoinSet;
use tracing::{error, info, warn};

/// 每条 chunk 连接分配一个自增 id,便于日志把 connected / idle timeout / server close / reconnect 串起来看。
static FUT_CONN_SEQ: AtomicU64 = AtomicU64::new(0);

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
        if symbols.is_empty() {
            warn!("Futures WS has no eligible symbols; waiting for engine:universe");
            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
            if let Some(fresh) = load_universe_symbols_checked(&redis_url).await {
                symbols = fresh;
            }
            continue;
        }
        if let Err(e) = connect_and_stream(&symbols, &redis_url, &tickers, &update_tx).await {
            error!(error = %e, "Futures WS disconnected");
        }
        warn!("Futures WS reconnecting in 2s...");
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        if let Some(fresh) = load_universe_symbols_checked(&redis_url).await {
            if fresh != symbols {
                info!(prev = symbols.len(), next = fresh.len(), "Futures WS universe updated on reconnect");
                symbols = fresh;
            }
        }
    }
}

async fn connect_and_stream(
    symbols: &[String],
    redis_url: &str,
    tickers: &Arc<DashMap<String, (TickerData, TickerData)>>,
    update_tx: &mpsc::UnboundedSender<String>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Futures @ticker has no executable bid/ask. Keep bookTicker for prices
    // and add markPrice@1s as a WS heartbeat so quiet books remain live.
    // Binance Combined Stream names are lowercase. Keep both the executable
    // book quote and mark-price heartbeat for quiet futures symbols.
    let streams: Vec<String> = symbols.iter().flat_map(|s| [
        format!("{}@bookTicker", s.to_ascii_lowercase()),
        format!("{}@markPrice@1s", s.to_ascii_lowercase()),
    ]).collect();

    let owned_chunks: Vec<Vec<String>> = streams
        .chunks(200)
        .map(|c| c.to_vec())
        .collect();

    let mut tasks: JoinSet<Result<(), Box<dyn std::error::Error + Send + Sync>>> = JoinSet::new();

    for chunk in owned_chunks {
        let stream_param = chunk.join("/");
        let url = format!(
            "wss://fstream.binance.com/stream?streams={}",
            stream_param
        );
        let num_streams = chunk.len();

        let tickers = tickers.clone();
        let update_tx = update_tx.clone();

        tasks.spawn(async move {
            let conn_id = FUT_CONN_SEQ.fetch_add(1, Ordering::Relaxed);
            let (ws, _) = tokio_tungstenite::connect_async(&url).await?;
            info!(conn_id, streams = num_streams, "Futures WS connected");

            // 保留 write 半边回 Pong 保活:原 `let (_, mut read)` 丢弃 write,收到 Binance Ping 也无法回 Pong
            // → 每 3min Ping、10min 内无 Pong 即被断 → 每 ~10min 一次无谓重连+feed 缺口。留 write 后可回 Pong。
            use tokio_tungstenite::tungstenite::Message;
            let (mut write, mut read) = ws.split();
            let idle = std::time::Duration::from_secs(WS_IDLE_TIMEOUT_SECS);

            loop {
                match tokio::time::timeout(idle, read.next()).await {
                    Err(_elapsed) => {
                        warn!(
                            conn_id,
                            streams = num_streams,
                            timeout_s = WS_IDLE_TIMEOUT_SECS,
                            "Futures WS idle timeout — half-open detected, triggering reconnect"
                        );
                        return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                            "idle timeout".into()
                        );
                    }
                    Ok(None) => {
                        return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                            "stream closed".into(),
                        );
                    }
                    Ok(Some(msg)) => {
                        let msg = msg?;
                        // 控制帧优先: Ping→回Pong保活; Close→立即Err触发整体重连(Binance 24h定期断/serverShutdown
                        // 升级窗口,不必等新鲜度看门狗的 600s 窗口)。下方 Text 处理体保持不变。
                        match &msg {
                            Message::Ping(payload) => {
                                if let Err(e) = write.send(Message::Pong(payload.clone())).await {
                                    warn!(conn_id, error = %e, "Futures WS pong failed — reconnecting");
                                    return Err::<(), Box<dyn std::error::Error + Send + Sync>>("pong failed".into());
                                }
                                continue;
                            }
                            Message::Close(frame) => {
                                info!(conn_id, ?frame, "Futures WS server close — reconnecting");
                                return Err::<(), Box<dyn std::error::Error + Send + Sync>>("server close".into());
                            }
                            _ => {}
                        }
                        if let tokio_tungstenite::tungstenite::Message::Text(text) = msg {
                            if let Ok(combined) = serde_json::from_str::<BinanceCombinedStream>(&text) {
                                let symbol = combined.data.symbol.clone();
                                let recv_ts = std::time::SystemTime::now()
                                    .duration_since(std::time::UNIX_EPOCH)
                                    .unwrap()
                                    .as_millis() as i64;
                                let ts = combined.data.event_time
                                    .or(combined.data.timestamp)
                                    .unwrap_or(recv_ts);

                                let bid = combined.data.bid_price;
                                let ask = combined.data.ask_price;
                                tickers.entry(symbol.clone())
                                    .and_modify(|pair| {
                                        if let (Some(bid), Some(ask)) = (bid, ask) {
                                            pair.1.bid = bid;
                                            pair.1.ask = ask;
                                            // Only executable bookTicker frames may
                                            // advance quote freshness. markPrice@1s
                                            // has no bid/ask and must not mask a
                                            // stalled order-book stream.
                                            pair.1.ts = ts;
                                            pair.1.recv_ts = recv_ts;
                                        }
                                    })
                                    .or_insert_with(|| {
                                        let quote = match (bid, ask) {
                                            (Some(bid), Some(ask)) => TickerData {
                                                bid,
                                                ask,
                                                ts,
                                                recv_ts,
                                            },
                                            // A mark-price heartbeat alone is not a
                                            // usable quote; leave the pair stale until
                                            // the first bookTicker frame arrives.
                                            _ => TickerData::default(),
                                        };
                                        (TickerData::default(), quote)
                                    });

                                let _ = update_tx.send(symbol);
                            }
                        }
                    }
                }
            }

            Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
        });
    }

    // 逐币新鲜度看门狗(per-stream): 合约腿 = tickers 的 .1。某 200-分片整段静默即强制重连。
    {
        let mon_symbols: Vec<String> = symbols.to_vec();
        let mon_tickers = tickers.clone();
        tasks.spawn(async move {
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
                            // Redis uses lower-case symbols; Binance frames
                            // populate the ticker map with upper-case keys.
                            let key = s.to_ascii_uppercase();
                            let last = mon_tickers
                                .get(key.as_str())
                                .map(|t| if t.1.recv_ts > 0 { t.1.recv_ts } else { t.1.ts })
                                .unwrap_or(0);
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
    }

    // Rebuild subscriptions promptly when the Python control plane changes
    // the merged execution/exit-only universe. A failed Redis read is not a
    // change and therefore cannot tear down a healthy feed.
    {
        let expected = symbols.to_vec();
        let redis_url = redis_url.to_owned();
        tasks.spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                let Some(fresh) = load_universe_symbols_checked(&redis_url).await else {
                    continue;
                };
                if fresh != expected {
                    return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                        "WS universe changed".into(),
                    );
                }
            }
        });
    }

    while let Some(result) = tasks.join_next().await {
        match result {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                tasks.abort_all();
                while tasks.join_next().await.is_some() {}
                return Err(error);
            }
            Err(error) => {
                tasks.abort_all();
                while tasks.join_next().await.is_some() {}
                return Err(format!("Futures WS task join error: {}", error).into());
            }
        }
    }
    Ok(())
}
