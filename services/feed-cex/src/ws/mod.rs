//! venue 泛型 WS 连接器。coin cex-engine 六项事故加固逐条移植:
//! 1. 每连接 ≤max_streams 分片订阅;conn_id 自增串日志
//! 2. 30s idle 半开看门狗(零帧 → 整体重连)
//! 3. 协议 Ping→回 Pong 保活(丢 write 半边曾致每 ~10min 被断);Text ping 模式供 OKX 类
//! 4. Close 帧 → 立即 Err 整体重连(24h 定期断/serverShutdown 不等看门狗)
//! 5. 逐币新鲜度分片看门狗:600s 窗口 + 40% 分片占比(bookTicker 仅价变才推,阈值须长窗口)
//! 6. 每次重连重读 universe,新币自动订阅
//!
//! 修正 coin 原版潜伏语义 bug:原 try_join_all(JoinHandle) 只对 panic(JoinError) 短路,
//! chunk 任务返回内层 Err 不会立即触发整体重连(靠外置 watchdog 兜底)。本版把内层 Result
//! 展平后再 try_join_all → 任一 chunk/监视器 Err 立即短路,并 abort 其余任务防孤儿连接续写。

pub mod venues;

use crate::config::load_universe;
use crate::types::TickerData;
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio::time::{sleep_until, Duration, Instant};
use tracing::{error, info, warn};
use venues::{PingMode, VenueSpec};

static CONN_SEQ: AtomicU64 = AtomicU64::new(0);

const WS_IDLE_TIMEOUT_SECS: u64 = 30;
const FRESH_CHECK_SECS: u64 = 20;
const SYMBOL_STALE_SECS: i64 = 600;
const CHUNK_STALE_FRACTION: f64 = 0.4;
const FRESH_GRACE_SECS: u64 = 75;
const RECONNECT_DELAY_SECS: u64 = 2;

type Err = Box<dyn std::error::Error + Send + Sync>;

/// 共享行情表:key = "venue:market:SYMBOL"(大写 symbol)。
pub type TickerMap = Arc<DashMap<String, TickerData>>;

pub fn composed_key(venue: &str, market: &str, symbol_upper: &str) -> String {
    format!("{venue}:{market}:{symbol_upper}")
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64
}

/// 一个 (venue,market) 的常驻任务:连接→断线→重连循环,重连时热重读 universe。
pub async fn run(
    spec: VenueSpec,
    initial_symbols: Vec<String>,
    redis_url: String,
    tickers: TickerMap,
    update_tx: mpsc::UnboundedSender<String>,
) {
    let tag = spec.key();
    let mut symbols = initial_symbols;
    loop {
        if let Err(e) = connect_and_stream(&spec, &symbols, &tickers, &update_tx).await {
            error!(feed = %tag, error = %e, "WS session ended");
        }
        warn!(feed = %tag, "reconnecting in {RECONNECT_DELAY_SECS}s...");
        tokio::time::sleep(Duration::from_secs(RECONNECT_DELAY_SECS)).await;
        let fresh = load_universe(&redis_url, spec.venue, spec.market).await;
        if !fresh.is_empty() && fresh != symbols {
            info!(feed = %tag, prev = symbols.len(), next = fresh.len(), "universe updated on reconnect");
            symbols = fresh;
        }
    }
}

async fn connect_and_stream(
    spec: &VenueSpec,
    symbols: &[String],
    tickers: &TickerMap,
    update_tx: &mpsc::UnboundedSender<String>,
) -> Result<(), Err> {
    let chunks: Vec<Vec<String>> = symbols
        .chunks(spec.max_streams_per_conn)
        .map(|c| c.to_vec())
        .collect();

    let mut join_futs: Vec<std::pin::Pin<Box<dyn std::future::Future<Output = Result<(), Err>> + Send>>> =
        Vec::new();
    let mut aborts = Vec::new();

    for chunk in chunks {
        let spec = *spec;
        let tickers = tickers.clone();
        let update_tx = update_tx.clone();
        let h = tokio::spawn(async move { chunk_session(spec, chunk, tickers, update_tx).await });
        aborts.push(h.abort_handle());
        join_futs.push(Box::pin(async move {
            match h.await {
                Ok(inner) => inner,
                Err(e) => Err(format!("chunk join: {e}").into()),
            }
        }));
    }

    // 逐币新鲜度分片看门狗:某分片 ≥40% 币 600s 未更新 → 判该 (venue,market) 半死 → 整体重连
    {
        let spec = *spec;
        let mon_symbols: Vec<String> = symbols.to_vec();
        let mon_tickers = tickers.clone();
        let h = tokio::spawn(async move {
            tokio::time::sleep(Duration::from_secs(FRESH_GRACE_SECS)).await;
            loop {
                tokio::time::sleep(Duration::from_secs(FRESH_CHECK_SECS)).await;
                let now = now_ms();
                for chunk in mon_symbols.chunks(spec.max_streams_per_conn) {
                    if chunk.is_empty() {
                        continue;
                    }
                    let stale = chunk
                        .iter()
                        .filter(|s| {
                            let key = composed_key(spec.venue, spec.market, &s.to_uppercase());
                            let last = mon_tickers.get(&key).map(|t| t.recv_ts).unwrap_or(0);
                            now - last > SYMBOL_STALE_SECS * 1000
                        })
                        .count();
                    if (stale as f64 / chunk.len() as f64) >= CHUNK_STALE_FRACTION {
                        warn!(feed = %spec.key(), stale, total = chunk.len(),
                              "per-symbol freshness: chunk mostly stale — forcing reconnect");
                        return Err::<(), Err>("chunk stale".into());
                    }
                }
            }
        });
        aborts.push(h.abort_handle());
        join_futs.push(Box::pin(async move {
            match h.await {
                Ok(inner) => inner,
                Err(e) => Err(format!("monitor join: {e}").into()),
            }
        }));
    }

    // 任一 chunk/监视器 Err → 立即短路;abort 全部任务防孤儿连接继续写行情(95 孤儿进程教训的进程内版)
    let result = futures_util::future::try_join_all(join_futs).await;
    for a in &aborts {
        a.abort();
    }
    result.map(|_| ())
}

async fn chunk_session(
    spec: VenueSpec,
    chunk: Vec<String>,
    tickers: TickerMap,
    update_tx: mpsc::UnboundedSender<String>,
) -> Result<(), Err> {
    use tokio_tungstenite::tungstenite::Message;

    let conn_id = CONN_SEQ.fetch_add(1, Ordering::Relaxed);
    let url = (spec.url)(&chunk);
    let (ws, _) = tokio_tungstenite::connect_async(&url).await?;
    info!(feed = %spec.key(), conn_id, streams = chunk.len(), "WS connected");

    let (mut write, mut read) = ws.split();

    for msg in (spec.subscribe)(&chunk) {
        write.send(Message::Text(msg)).await?;
    }

    let idle = Duration::from_secs(WS_IDLE_TIMEOUT_SECS);
    let mut idle_deadline = Instant::now() + idle;
    let (ping_payload, ping_period) = match spec.ping {
        PingMode::Text { payload, every_secs } => (Some(payload), Duration::from_secs(every_secs)),
        PingMode::Protocol => (None, Duration::from_secs(3600)),
    };
    let mut next_ping = Instant::now() + ping_period;

    loop {
        tokio::select! {
            // half-open 看门狗:超时零帧 → Err → 短路整体重连
            _ = sleep_until(idle_deadline) => {
                warn!(feed = %spec.key(), conn_id, timeout_s = WS_IDLE_TIMEOUT_SECS,
                      "WS idle timeout — half-open detected, reconnecting");
                return Err("idle timeout".into());
            }
            // 客户端文本 ping(OKX 类;币安 Protocol 模式下周期极长,等效关闭)
            _ = sleep_until(next_ping), if ping_payload.is_some() => {
                if let Some(p) = ping_payload {
                    if let Err(e) = write.send(Message::Text(p.to_string())).await {
                        warn!(feed = %spec.key(), conn_id, error = %e, "text ping failed — reconnecting");
                        return Err("text ping failed".into());
                    }
                }
                next_ping = Instant::now() + ping_period;
            }
            maybe = read.next() => {
                let msg = match maybe {
                    None => break,          // 流正常关闭 → Ok → 上层照样重连
                    Some(m) => m?,
                };
                idle_deadline = Instant::now() + idle;
                match &msg {
                    Message::Ping(payload) => {
                        if let Err(e) = write.send(Message::Pong(payload.clone())).await {
                            warn!(feed = %spec.key(), conn_id, error = %e, "pong failed — reconnecting");
                            return Err("pong failed".into());
                        }
                        continue;
                    }
                    Message::Close(frame) => {
                        info!(feed = %spec.key(), conn_id, ?frame, "server close — reconnecting");
                        return Err("server close".into());
                    }
                    _ => {}
                }
                if let Message::Text(text) = msg {
                    if let Some((symbol, td)) = (spec.parse)(&text, now_ms()) {
                        let key = composed_key(spec.venue, spec.market, &symbol);
                        tickers.insert(key.clone(), td);
                        let _ = update_tx.send(key);
                    }
                }
            }
        }
    }
    Ok(())
}
