// Quant Hedge WebSocket HUB — 生产版 (Phase 1 + 鉴权同源/连接数指标)
//
// 架构: Python 后端 _ws_broadcaster 每轮 PUBLISH 快照到 Redis `qh:ws:snapshot`,
//   本 HUB 订阅该频道 → 扇出给所有已鉴权 WS 连接(Rust 高并发, 卸载 Python GIL)。
//
// 鉴权(同源改造): 客户端首帧发 {"license_key":"..."}。
//   主判据 = 查 Postgres users 表(license 有效且 status 非 banned/disabled),
//   与 Python /ws/stream 完全同源 → 不再依赖易过期的 qh:session:{lk}(24h TTL 悬崖已消除)。
//   DB 不可达时降级回退 Redis qh:session:{lk}(避免 DB 抖动引入新故障面)。
//
// 心跳: 每 5s SET qh:ws:hub_alive=1 EX 10(有连接时)→ Python 据此持续算快照并 PUBLISH。
//        每 5s SET qh:ws:hub_clients=<真实连接数> EX 15 → Python /admin/system 读它显示真实在线。
// 新连接: 立即回 qh:ws:last_snapshot(Python 每轮 setex 的最近一帧), 免等下一个广播周期。
//
// 灰度/回滚: nginx /ws 指向本 HUB(9091) 或 Python(8090), 改 upstream 即切, 秒级回滚。

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpListener;
use tokio::sync::broadcast;
use redis::AsyncCommands;

const RNS: &str = "qh:";

struct Hub {
    tx: broadcast::Sender<String>,
    clients: DashMap<u64, ()>,
    next_id: AtomicU64,
}
impl Hub {
    fn new() -> Arc<Self> {
        let (tx, _) = broadcast::channel(2048);
        Arc::new(Hub { tx, clients: DashMap::new(), next_id: AtomicU64::new(1) })
    }
}

/// 订阅 Redis qh:ws:snapshot → 广播给所有连接。断线自动重连。
async fn redis_subscriber(hub: Arc<Hub>, url: String) {
    loop {
        if let Err(e) = run_sub(&hub, &url).await {
            tracing::error!("subscriber error: {e}; reconnect in 3s");
        }
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
}
async fn run_sub(hub: &Arc<Hub>, url: &str) -> redis::RedisResult<()> {
    let client = redis::Client::open(url)?;
    let mut pubsub = client.get_async_pubsub().await?;
    pubsub.subscribe(format!("{RNS}ws:snapshot")).await?;
    tracing::info!("subscribed {RNS}ws:snapshot");
    let mut stream = pubsub.on_message();
    while let Some(msg) = stream.next().await {
        if let Ok(payload) = msg.get_payload::<String>() {
            let _ = hub.tx.send(payload);
        }
    }
    Ok(())
}

/// 每 5s: (有连接时)刷 hub_alive TTL 告知 Python 持续算快照; 并写真实连接数 hub_clients(供 /admin/system)。
async fn heartbeat(hub: Arc<Hub>, url: String) {
    let client = match redis::Client::open(url) { Ok(c)=>c, Err(_)=>return };
    loop {
        if let Ok(mut con) = client.get_multiplexed_async_connection().await {
            let n = hub.clients.len();
            if n > 0 {
                let _: Result<(),_> = con.set_ex(format!("{RNS}ws:hub_alive"), "1", 10).await;
            }
            // 真实在线连接数(即使为 0 也写, 让面板归零; 15s TTL: hub 挂掉后自动过期)
            let _: Result<(),_> = con.set_ex(format!("{RNS}ws:hub_clients"), n as i64, 15).await;
        }
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

/// 校验 license_key。主判据=Postgres users(license 有效且未封禁/停用), 与 Python /ws/stream 同源。
/// DB 不可达时降级回退 Redis qh:session:{lk}(避免 DB 抖动放大为鉴权全挂)。
async fn auth_ok(redis_url: &str, dsn: &str, lk: &str) -> bool {
    if lk.is_empty() { return false; }
    match auth_db(dsn, lk).await {
        Some(ok) => ok,                       // DB 可达: 以库为准(Some(true/false))
        None => auth_session(redis_url, lk).await,  // DB 不可达: 回退 session 键
    }
}
/// 查库: 返回 Some(true)=有效放行 / Some(false)=存在但封禁停用或不存在 / None=DB 连接失败(交回退)。
async fn auth_db(dsn: &str, lk: &str) -> Option<bool> {
    let (client, connection) = match tokio_postgres::connect(dsn, tokio_postgres::NoTls).await {
        Ok(v) => v,
        Err(e) => { tracing::warn!("auth_db connect fail: {e}"); return None; }
    };
    // 连接驱动需单独 spawn; 查询完自然结束
    let handle = tokio::spawn(async move { let _ = connection.await; });
    let row = client
        .query_opt("SELECT status FROM users WHERE license_key=$1", &[&lk])
        .await;
    handle.abort();
    match row {
        Ok(Some(r)) => {
            let status: String = r.get(0);
            Some(status != "banned" && status != "disabled")
        }
        Ok(None) => Some(false),               // license 不存在
        Err(e) => { tracing::warn!("auth_db query fail: {e}"); None }
    }
}
async fn auth_session(redis_url: &str, lk: &str) -> bool {
    let client = match redis::Client::open(redis_url) { Ok(c)=>c, Err(_)=>return false };
    let mut con = match client.get_multiplexed_async_connection().await { Ok(c)=>c, Err(_)=>return false };
    con.exists(format!("{RNS}session:{lk}")).await.unwrap_or(false)
}
/// 取最近一帧快照(新连接立即回)。
async fn last_snapshot(url: &str) -> Option<String> {
    let client = redis::Client::open(url).ok()?;
    let mut con = client.get_multiplexed_async_connection().await.ok()?;
    con.get(format!("{RNS}ws:last_snapshot")).await.ok()
}

async fn handle_conn(hub: Arc<Hub>, stream: tokio::net::TcpStream, redis_url: String, dsn: String) {
    let ws = match tokio_tungstenite::accept_async(stream).await { Ok(w)=>w, Err(_)=>return };
    let (mut write, mut read) = ws.split();
    use tokio_tungstenite::tungstenite::Message;

    // 首帧鉴权(5s 超时)
    let first = tokio::time::timeout(std::time::Duration::from_secs(5), read.next()).await;
    let lk = match first {
        Ok(Some(Ok(Message::Text(t)))) => serde_json::from_str::<serde_json::Value>(&t).ok()
            .and_then(|v| v.get("license_key").and_then(|x| x.as_str()).map(String::from)).unwrap_or_default(),
        _ => { let _ = write.send(Message::Close(None)).await; return; }
    };
    if !auth_ok(&redis_url, &dsn, &lk).await {
        let _ = write.send(Message::Text("{\"type\":\"error\",\"msg\":\"auth failed\"}".into())).await;
        let _ = write.send(Message::Close(None)).await; return;
    }

    let id = hub.next_id.fetch_add(1, Ordering::Relaxed);
    hub.clients.insert(id, ());
    // 立即回最近一帧
    if let Some(snap) = last_snapshot(&redis_url).await { let _ = write.send(Message::Text(snap)).await; }

    let mut rx = hub.tx.subscribe();
    let pump = tokio::spawn(async move {
        while let Ok(msg) = rx.recv().await {
            if write.send(Message::Text(msg)).await.is_err() { break; }
        }
    });
    // 上行: ping / 断开
    while let Some(m) = read.next().await { if m.is_err() { break; } }
    pump.abort();
    hub.clients.remove(&id);
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().init();
    let url = std::env::var("QH_REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379/3".into());
    let bind = std::env::var("QH_HUB_BIND").unwrap_or_else(|_| "127.0.0.1:9091".into());
    let dsn = std::env::var("QH_DB_DSN")
        .unwrap_or_else(|_| "host=127.0.0.1 dbname=quanthedge user=quanthedge".into());
    let hub = Hub::new();
    tokio::spawn(redis_subscriber(hub.clone(), url.clone()));
    tokio::spawn(heartbeat(hub.clone(), url.clone()));
    let listener = TcpListener::bind(&bind).await.expect("bind");
    tracing::info!("QH WS HUB listening on {bind} (auth=db+session-fallback)");
    loop {
        if let Ok((stream, _)) = listener.accept().await {
            let (h, u, d) = (hub.clone(), url.clone(), dsn.clone());
            tokio::spawn(handle_conn(h, stream, u, d));
        }
    }
}
