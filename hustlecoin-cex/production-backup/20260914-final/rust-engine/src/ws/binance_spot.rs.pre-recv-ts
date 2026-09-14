use crate::config::load_universe_symbols;
use crate::types::{BinanceCombinedStream, TickerData};
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::sync::mpsc;
use tracing::{error, info, warn};

/// 每条 chunk 连接分配一个自增 id,便于日志把 connected / idle timeout / server close / reconnect 串起来看。
static SPOT_CONN_SEQ: AtomicU64 = AtomicU64::new(0);

/// half-open 看门狗: 超过此秒数未收任何帧 → 视为 TCP 半开假死 → 返回 Err 触发重连。
const WS_IDLE_TIMEOUT_SECS: u64 = 30;

/// 逐币(per-stream)新鲜度看门狗: 整连接 idle 只能发现「一帧都不来」的全死;但实测出现过
/// 「连接还在、某 200-分片整段不再推帧」的半死(A–M 段冻结 9.6h 而 idle 没触发)。故再加一层:
/// (重)连后宽限 FRESH_GRACE_SECS 铺底,之后每 FRESH_CHECK_SECS 扫一次,任一分片内 ≥CHUNK_STALE_FRACTION
/// 的币超过 SYMBOL_STALE_SECS 未更新 → 判该连接死 → 返回 Err 触发整体重连。按「分片比例」判定可容忍
/// 零星不活跃币(只有整片静默才越阈),阈值给足余量避免误杀。
// 阈值按实测稳态校准:bookTicker 仅价变时推,健康态某分片内 stale>300s 仅 ~21%(stale>60s 高达 ~34%,
// 不可用)。取 300s 窗口 + 80% 分片占比 → 健康永不触发、整片死(=100%)必触发。30s idle 看门狗仍负责
// 快速抓「整连接零帧」;本 monitor 是「连接还在、流静默」的保守兜底,故窗口放长避免误重连。
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
            let conn_id = SPOT_CONN_SEQ.fetch_add(1, Ordering::Relaxed);
            let (ws, _) = tokio_tungstenite::connect_async(&url).await?;
            info!(conn_id, streams = num_streams, "Spot WS connected");

            // 保留 write 半边回 Pong 保活:原 `let (_, mut read)` 丢弃 write,收到 Binance Ping 也无法回 Pong
            // → 每 3min Ping、10min 内无 Pong 即被断 → 每 ~10min 一次无谓重连+feed 缺口。留 write 后可回 Pong。
            use tokio_tungstenite::tungstenite::Message;
            let (mut write, mut read) = ws.split();
            let idle = std::time::Duration::from_secs(WS_IDLE_TIMEOUT_SECS);

            loop {
                // half-open 看门狗: 超时未收帧 → Err → chunk task 结束 → try_join_all 短路 → 整体重连
                match tokio::time::timeout(idle, read.next()).await {
                    Err(_elapsed) => {
                        warn!(
                            conn_id,
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
                        // 控制帧优先: Ping→回Pong保活; Close→立即Err触发整体重连(Binance 24h定期断/serverShutdown
                        // 升级窗口,不必等新鲜度看门狗的 600s 窗口)。下方 Text 处理体保持不变。
                        match &msg {
                            Message::Ping(payload) => {
                                if let Err(e) = write.send(Message::Pong(payload.clone())).await {
                                    warn!(conn_id, error = %e, "Spot WS pong failed — reconnecting");
                                    return Err::<(), Box<dyn std::error::Error + Send + Sync>>("pong failed".into());
                                }
                                continue;
                            }
                            Message::Close(frame) => {
                                info!(conn_id, ?frame, "Spot WS server close — reconnecting");
                                return Err::<(), Box<dyn std::error::Error + Send + Sync>>("server close".into());
                            }
                            _ => {}
                        }
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

    // 逐币新鲜度看门狗(per-stream): 现货腿 = tickers 的 .0。某 200-分片整段静默即强制重连。
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
                            let last = mon_tickers.get(s.as_str()).map(|t| t.0.ts).unwrap_or(0);
                            now - last > SYMBOL_STALE_SECS * 1000
                        })
                        .count();
                    if (stale as f64 / chunk.len() as f64) >= CHUNK_STALE_FRACTION {
                        warn!(
                            stale,
                            total = chunk.len(),
                            "Spot per-symbol freshness: chunk mostly stale — forcing reconnect"
                        );
                        return Err::<(), Box<dyn std::error::Error + Send + Sync>>(
                            "spot chunk stale".into(),
                        );
                    }
                }
            }
        });
        handles.push(monitor);
    }

    // try_join_all: 任一 chunk 出错立即返回 Err → 外层 loop 2s 后整体重连。
    // 修复原因: 原 `for h in handles { h.await? }` 顺序等待,某 chunk TCP 半开永久阻塞则整体卡死。
    let results: Result<Vec<_>, _> = futures_util::future::try_join_all(handles).await;
    if let Err(e) = results {
        return Err(format!("Spot WS chunk join error: {}", e).into());
    }
    Ok(())
}
