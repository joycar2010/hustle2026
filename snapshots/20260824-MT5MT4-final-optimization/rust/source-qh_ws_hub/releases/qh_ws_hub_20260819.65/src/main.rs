// Quant Hedge WebSocket HUB — 生产版 (严格用户隔离 + 慢客户端恢复)
//
// 架构: Python 后端每轮逐用户 PUBLISH 快照到 Redis `qh:ws:snapshot`(帧带 "u":username),
//   本 HUB 订阅该频道 → 只转发给该用户的已鉴权连接。无有效 "u" 的帧一律丢弃。
//
// 鉴权(同源改造): 客户端首帧发 {"license_key":"..."}。
//   主判据 = 查 Postgres users 表(license 有效且 status 非 banned/disabled), 同时取 username 供路由,
//   与 Python /ws/stream 完全同源。DB 不可达时拒绝新连接，绝不以未知用户名降级放行。
//
// 心跳: 每 5s SET qh:ws:hub_alive=1 EX 10(有连接时)→ Python 据此持续算快照并 PUBLISH。
//        每 5s SET qh:ws:hub_clients=<真实连接数> EX 15 → Python /admin/system 读它显示真实在线。
// 新连接: 立即回 qh:ws:last_snapshot:{user}(Python 每轮 setex), 且再次校验帧归属。
//
// 灰度/回滚: nginx /ws 指向本 HUB(9091) 或 Python(8090), 改 upstream 即切, 秒级回滚。

use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use redis::AsyncCommands;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::net::TcpListener;
use tokio::sync::{broadcast, Notify};

const RNS: &str = "qh:";

struct Hub {
    snapshot_tx: broadcast::Sender<Arc<RoutedFrame>>,
    terminal_tx: broadcast::Sender<Arc<RoutedFrame>>,
    clients: DashMap<u64, String>,
    next_id: AtomicU64,
    unroutable_frames: AtomicU64,
    presence_changed: Notify,
}

#[derive(Debug)]
struct RoutedFrame {
    user: String,
    payload: String,
    terminal: bool,
}

#[derive(Debug, PartialEq, Eq)]
enum RouteError {
    InvalidEnvelope,
    MissingUser,
    EmptyUser,
}

#[derive(serde::Deserialize)]
struct RouteEnvelope {
    u: Option<String>,
    #[serde(rename = "type")]
    frame_type: Option<String>,
}

fn parse_routed_frame(payload: String) -> Result<RoutedFrame, RouteError> {
    let route: RouteEnvelope =
        serde_json::from_str(&payload).map_err(|_| RouteError::InvalidEnvelope)?;
    let user = route.u.ok_or(RouteError::MissingUser)?;
    if user.is_empty() {
        return Err(RouteError::EmptyUser);
    }
    let terminal = route.frame_type.as_deref() == Some("position_projection");
    Ok(RoutedFrame { user, payload, terminal })
}
impl Hub {
    fn new() -> Arc<Self> {
        let (snapshot_tx, _) = broadcast::channel(2048);
        // Terminal projections are state-changing evidence rather than
        // replaceable quote snapshots. Give them a separate, larger lane so
        // a slow client cannot discard a projection while coalescing ticks.
        let (terminal_tx, _) = broadcast::channel(8192);
        Arc::new(Hub {
            snapshot_tx,
            terminal_tx,
            clients: DashMap::new(),
            next_id: AtomicU64::new(1),
            unroutable_frames: AtomicU64::new(0),
            presence_changed: Notify::new(),
        })
    }

    fn users(&self) -> Vec<String> {
        let mut users: Vec<String> = self
            .clients
            .iter()
            .map(|entry| entry.value().clone())
            .collect();
        users.sort();
        users.dedup();
        users
    }

    fn record_unroutable_frame(&self, error: RouteError) {
        let count = self.unroutable_frames.fetch_add(1, Ordering::Relaxed) + 1;
        if should_log_unroutable(count) {
            tracing::warn!(?error, count, "dropped unroutable websocket snapshots");
        }
    }
}

fn should_log_unroutable(count: u64) -> bool {
    count == 1 || count % 100 == 0
}

/// 订阅 Redis qh:ws:snapshot → 验证路由标签后广播给连接任务。断线自动重连。
async fn redis_subscriber(hub: Arc<Hub>, url: String, terminal: bool) {
    loop {
        if let Err(e) = run_sub(&hub, &url, terminal).await {
            tracing::error!("subscriber error: {e}; reconnect in 3s");
        }
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
}
async fn run_sub(hub: &Arc<Hub>, url: &str, terminal: bool) -> redis::RedisResult<()> {
    let client = redis::Client::open(url)?;
    let mut pubsub = client.get_async_pubsub().await?;
    let channel = if terminal { "ws:terminal" } else { "ws:snapshot" };
    pubsub.subscribe(format!("{RNS}{channel}")).await?;
    tracing::info!("subscribed {RNS}{channel}");
    let mut stream = pubsub.on_message();
    while let Some(msg) = stream.next().await {
        if let Ok(payload) = msg.get_payload::<String>() {
            match parse_routed_frame(payload) {
                Ok(frame) if frame.terminal == terminal => {
                    let sender = if terminal { &hub.terminal_tx } else { &hub.snapshot_tx };
                    let _ = sender.send(Arc::new(frame));
                }
                Ok(_) => {
                    // During rollout Python publishes terminal frames to the
                    // legacy snapshot channel as well. The dedicated Hub
                    // subscriber must not deliver that copy twice.
                }
                Err(error) => hub.record_unroutable_frame(error),
            }
        }
    }
    Ok(())
}

/// 每 5s: (有连接时)刷 hub_alive TTL 告知 Python 持续算快照; 并写真实连接数 hub_clients(供 /admin/system)。
async fn heartbeat(hub: Arc<Hub>, url: String) {
    let client = match redis::Client::open(url) {
        Ok(c) => c,
        Err(_) => return,
    };
    loop {
        if let Ok(mut con) = client.get_multiplexed_async_connection().await {
            let n = hub.clients.len();
            let users = serde_json::to_string(&hub.users()).unwrap_or_else(|_| "[]".into());
            if n > 0 {
                let _: Result<(), _> = con.set_ex(format!("{RNS}ws:hub_alive"), "1", 10).await;
            }
            // 真实在线连接数(即使为 0 也写, 让面板归零; 15s TTL: hub 挂掉后自动过期)
            let _: Result<(), _> = con
                .set_ex(format!("{RNS}ws:hub_clients"), n as i64, 15)
                .await;
            // 在线用户名只用于让 Python 逐用户产帧；排序去重使内容稳定，同一用户多标签只发布一份。
            let _: Result<(), _> = con.set_ex(format!("{RNS}ws:hub_users"), users, 15).await;
        }
        tokio::select! {
            _ = tokio::time::sleep(std::time::Duration::from_secs(5)) => {}
            _ = hub.presence_changed.notified() => {}
        }
    }
}

/// 校验 license_key 并取 username(供按用户路由)。数据库异常时 fail closed。
async fn auth_user(dsn: &str, lk: &str) -> Option<String> {
    if lk.is_empty() {
        return None;
    }
    resolve_db_auth(auth_db(dsn, lk).await)
}

fn resolve_db_auth(result: Option<Option<String>>) -> Option<String> {
    result.flatten().filter(|user| !user.is_empty())
}

/// 查库: 返回 Some(Some(username))=有效放行 / Some(None)=封禁停用或不存在 / None=DB 连接失败(拒绝)。
async fn auth_db(dsn: &str, lk: &str) -> Option<Option<String>> {
    let (client, connection) = match tokio_postgres::connect(dsn, tokio_postgres::NoTls).await {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!("auth_db connect fail: {e}");
            return None;
        }
    };
    // 连接驱动需单独 spawn; 查询完自然结束
    let handle = tokio::spawn(async move {
        let _ = connection.await;
    });
    let row = client
        .query_opt(
            "SELECT status,username FROM users WHERE license_key=$1",
            &[&lk],
        )
        .await;
    handle.abort();
    match row {
        Ok(Some(r)) => {
            let status: String = r.get(0);
            let username: String = r.get(1);
            if status != "banned" && status != "disabled" {
                Some(Some(username))
            } else {
                Some(None)
            }
        }
        Ok(None) => Some(None), // license 不存在
        Err(e) => {
            tracing::warn!("auth_db query fail: {e}");
            None
        }
    }
}
/// 取最近一帧快照(新连接立即回)，并校验缓存内容仍属于该用户。
async fn last_snapshot(url: &str, user: &str) -> Option<String> {
    let client = redis::Client::open(url).ok()?;
    let mut con = client.get_multiplexed_async_connection().await.ok()?;
    let payload: String = con
        .get(format!("{RNS}ws:last_snapshot:{user}"))
        .await
        .ok()?;
    match parse_routed_frame(payload) {
        Ok(frame) if frame.user == user => Some(frame.payload),
        Ok(frame) => {
            tracing::warn!(expected_user=%user, actual_user=%frame.user,
                           "dropped cross-user cached websocket snapshot");
            None
        }
        Err(error) => {
            tracing::warn!(expected_user=%user, ?error,
                           "dropped unroutable cached websocket snapshot");
            None
        }
    }
}

async fn last_terminal(url: &str, user: &str) -> Option<String> {
    let client = redis::Client::open(url).ok()?;
    let mut con = client.get_multiplexed_async_connection().await.ok()?;
    let payload: String = con
        .get(format!("{RNS}ws:last_terminal:{user}"))
        .await
        .ok()?;
    match parse_routed_frame(payload) {
        Ok(frame) if frame.user == user && frame.terminal => Some(frame.payload),
        Ok(frame) => {
            tracing::warn!(expected_user=%user, actual_user=%frame.user,
                           "dropped cross-user or non-terminal cached projection");
            None
        }
        Err(error) => {
            tracing::warn!(expected_user=%user, ?error,
                           "dropped unroutable cached terminal projection");
            None
        }
    }
}

async fn next_frame_for_user(
    rx: &mut broadcast::Receiver<Arc<RoutedFrame>>,
    user: &str,
) -> Option<(Arc<RoutedFrame>, u64)> {
    let mut skipped = 0_u64;
    loop {
        match rx.recv().await {
            Ok(frame) if frame.user == user => return Some((frame, skipped)),
            Ok(_) => continue,
            Err(broadcast::error::RecvError::Lagged(count)) => {
                skipped = skipped.saturating_add(count);
                // Drain retained snapshots and keep only this user's newest frame.
                // Snapshots are replaceable state, not an event log.
                let mut latest = None;
                loop {
                    match rx.try_recv() {
                        Ok(frame) if frame.user == user => latest = Some(frame),
                        Ok(_) => {}
                        Err(broadcast::error::TryRecvError::Lagged(more)) => {
                            skipped = skipped.saturating_add(more);
                            latest = None;
                        }
                        Err(broadcast::error::TryRecvError::Empty) => break,
                        Err(broadcast::error::TryRecvError::Closed) => {
                            return latest.map(|frame| (frame, skipped));
                        }
                    }
                }
                if let Some(frame) = latest {
                    return Some((frame, skipped));
                }
            }
            Err(broadcast::error::RecvError::Closed) => return None,
        }
    }
}

async fn handle_conn(hub: Arc<Hub>, stream: tokio::net::TcpStream, redis_url: String, dsn: String) {
    let ws = match tokio_tungstenite::accept_async(stream).await {
        Ok(w) => w,
        Err(_) => return,
    };
    let (mut write, mut read) = ws.split();
    use tokio_tungstenite::tungstenite::Message;

    // 首帧鉴权(5s 超时)
    let first = tokio::time::timeout(std::time::Duration::from_secs(5), read.next()).await;
    let lk = match first {
        Ok(Some(Ok(Message::Text(t)))) => serde_json::from_str::<serde_json::Value>(&t)
            .ok()
            .and_then(|v| {
                v.get("license_key")
                    .and_then(|x| x.as_str())
                    .map(String::from)
            })
            .unwrap_or_default(),
        _ => {
            let _ = write.send(Message::Close(None)).await;
            return;
        }
    };
    let user = match auth_user(&dsn, &lk).await {
        Some(u) => u,
        None => {
            let _ = write
                .send(Message::Text(
                    "{\"type\":\"error\",\"msg\":\"auth failed\"}".into(),
                ))
                .await;
            let _ = write.send(Message::Close(None)).await;
            return;
        }
    };

    let id = hub.next_id.fetch_add(1, Ordering::Relaxed);
    hub.clients.insert(id, user.clone());
    hub.presence_changed.notify_one();
    // 立即回最近一帧(按用户)
    if let Some(snap) = last_snapshot(&redis_url, &user).await {
        let _ = write.send(Message::Text(snap)).await;
    }
    if let Some(terminal) = last_terminal(&redis_url, &user).await {
        let _ = write.send(Message::Text(terminal)).await;
    }

    let mut snapshot_rx = hub.snapshot_tx.subscribe();
    let mut terminal_rx = hub.terminal_tx.subscribe();
    let uname = user.clone();
    let mut pump = tokio::spawn(async move {
        loop {
            let next = tokio::select! {
                biased;
                value = next_frame_for_user(&mut terminal_rx, &uname) => {
                    value.map(|(frame, skipped)| (frame, skipped, "terminal"))
                }
                value = next_frame_for_user(&mut snapshot_rx, &uname) => {
                    value.map(|(frame, skipped)| (frame, skipped, "snapshot"))
                }
            };
            let Some((frame, skipped, lane)) = next else { break; };
            if skipped > 0 {
                tracing::warn!(client_id=id, user=%uname, skipped, lane,
                               "websocket receiver lagged; resumed at live edge");
            }
            if write
                .send(Message::Text(frame.payload.clone().into()))
                .await
                .is_err()
            {
                break;
            }
        }
    });
    // 上行: ping / 断开
    tokio::select! {
        _ = async { while let Some(m) = read.next().await { if m.is_err() { break; } } } => {
            pump.abort();
        }
        _ = &mut pump => {}
    }
    hub.clients.remove(&id);
    hub.presence_changed.notify_one();
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().init();
    let url = std::env::var("QH_REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379/3".into());
    let bind = std::env::var("QH_HUB_BIND").unwrap_or_else(|_| "127.0.0.1:9091".into());
    let dsn = std::env::var("QH_DB_DSN")
        .unwrap_or_else(|_| "host=127.0.0.1 dbname=quanthedge user=quanthedge".into());
    let hub = Hub::new();
    tokio::spawn(redis_subscriber(hub.clone(), url.clone(), false));
    tokio::spawn(redis_subscriber(hub.clone(), url.clone(), true));
    tokio::spawn(heartbeat(hub.clone(), url.clone()));
    let listener = TcpListener::bind(&bind).await.expect("bind");
    tracing::info!("QH WS HUB listening on {bind} (auth=db-fail-closed, strict per-user routing, lag recovery)");
    loop {
        if let Ok((stream, _)) = listener.accept().await {
            let (h, u, d) = (hub.clone(), url.clone(), dsn.clone());
            tokio::spawn(handle_conn(h, stream, u, d));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{timeout, Duration};

    fn frame(user: &str, seq: u64) -> Arc<RoutedFrame> {
        Arc::new(
            parse_routed_frame(format!(
                "{{\"type\":\"snapshot\",\"u\":{},\"seq\":{seq}}}",
                serde_json::to_string(user).unwrap()
            ))
            .unwrap(),
        )
    }

    fn terminal_frame(user: &str, seq: u64) -> Arc<RoutedFrame> {
        Arc::new(
            parse_routed_frame(format!(
                "{{\"type\":\"position_projection\",\"u\":{},\"projection_sequence\":{seq}}}",
                serde_json::to_string(user).unwrap()
            ))
            .unwrap(),
        )
    }

    #[test]
    fn route_parser_accepts_escaped_username() {
        let parsed =
            parse_routed_frame(r#"{"type":"snapshot","u":"alice\"ops","fast":{}}"#.to_string())
                .unwrap();
        assert_eq!(parsed.user, "alice\"ops");
        assert!(!parsed.terminal);
        assert!(parse_routed_frame(
            r#"{"type":"position_projection","u":"alice"}"#.into()
        ).unwrap().terminal);
    }

    #[test]
    fn route_parser_rejects_unroutable_frames() {
        assert_eq!(
            parse_routed_frame(r#"{"type":"snapshot"}"#.into()).unwrap_err(),
            RouteError::MissingUser
        );
        assert_eq!(
            parse_routed_frame(r#"{"type":"snapshot","u":""}"#.into()).unwrap_err(),
            RouteError::EmptyUser
        );
        assert_eq!(
            parse_routed_frame(r#"{"type":"snapshot","u":7}"#.into()).unwrap_err(),
            RouteError::InvalidEnvelope
        );
        assert_eq!(
            parse_routed_frame("not-json".into()).unwrap_err(),
            RouteError::InvalidEnvelope
        );
    }

    #[test]
    fn database_failure_and_unknown_identity_fail_closed() {
        assert_eq!(resolve_db_auth(None), None);
        assert_eq!(resolve_db_auth(Some(None)), None);
        assert_eq!(resolve_db_auth(Some(Some(String::new()))), None);
        assert_eq!(
            resolve_db_auth(Some(Some("alice".into()))),
            Some("alice".into())
        );
    }

    #[test]
    fn connected_users_are_sorted_and_deduplicated() {
        let hub = Hub::new();
        hub.clients.insert(3, "bob".into());
        hub.clients.insert(1, "alice".into());
        hub.clients.insert(2, "bob".into());
        assert_eq!(hub.users(), vec!["alice".to_string(), "bob".to_string()]);
        assert_eq!(
            serde_json::to_string(&hub.users()).unwrap(),
            r#"["alice","bob"]"#
        );
    }

    #[test]
    fn unroutable_log_is_rate_limited() {
        assert!(should_log_unroutable(1));
        assert!(!should_log_unroutable(2));
        assert!(!should_log_unroutable(99));
        assert!(should_log_unroutable(100));
        assert!(should_log_unroutable(200));
    }

    #[tokio::test]
    async fn receiver_never_returns_another_users_frame() {
        let (tx, _) = broadcast::channel(8);
        let mut rx = tx.subscribe();
        tx.send(frame("bob", 1)).unwrap();
        tx.send(frame("alice", 2)).unwrap();

        let (received, skipped) = timeout(
            Duration::from_secs(1),
            next_frame_for_user(&mut rx, "alice"),
        )
        .await
        .unwrap()
        .unwrap();
        assert_eq!(received.user, "alice");
        assert!(received.payload.contains("\"seq\":2"));
        assert_eq!(skipped, 0);
    }

    #[tokio::test]
    async fn lagged_receiver_recovers_at_live_edge() {
        let (tx, _) = broadcast::channel(2);
        let mut rx = tx.subscribe();
        tx.send(frame("alice", 1)).unwrap();
        tx.send(frame("bob", 2)).unwrap();
        tx.send(frame("alice", 3)).unwrap();

        let (received, skipped) = timeout(
            Duration::from_secs(1),
            next_frame_for_user(&mut rx, "alice"),
        )
        .await
        .unwrap()
        .unwrap();
        assert!(skipped > 0);
        assert!(received.payload.contains("\"seq\":3"));
    }

    #[tokio::test]
    async fn terminal_lane_keeps_projection_events_independent_of_snapshot_flood() {
        let (snapshot_tx, _) = broadcast::channel(2);
        let (terminal_tx, _) = broadcast::channel(32);
        let mut terminal_rx = terminal_tx.subscribe();
        for seq in 1..=20 {
            let _ = snapshot_tx.send(frame("alice", seq));
            terminal_tx.send(terminal_frame("alice", seq)).unwrap();
        }
        let mut seen = 0;
        while let Ok(Some((value, _))) = timeout(
            Duration::from_millis(50),
            next_frame_for_user(&mut terminal_rx, "alice"),
        ).await {
            assert!(value.terminal);
            seen += 1;
        }
        assert_eq!(seen, 20);
    }
}
