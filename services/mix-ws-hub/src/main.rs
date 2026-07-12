// HustleCoin Mix WebSocket HUB — qh-ws-hub 生产模式适配。
//
// 架构: 纯中继,不算业务 —— mix-backend(Python)负责把 position:updates 等预打包帧
//   PUBLISH 到 `mix:ws:frames`;本 HUB 订阅四路 → 扇出给已鉴权 WS 连接:
//     dcm:notify:broadcast → {"channel":"marquee",...}     (dcm 全服务跑马灯)
//     dcm:route:updates    → {"channel":"route:updates",...}
//     mix:ws:frames        → 透传(帧内自带 channel 字段)
//     mix:user:{uid}       → {"channel":"user_event",...} 仅发给该 uid 的连接(按用户路由)
//   另每 20s 广播 {"channel":"hb"}(客户端 >60s 静默看门狗依赖此帧)。
//
// 鉴权(URL ?token=,与 Python require_viewer 三轨完全同源):
//   1) MIX_READONLY_TOKEN 直比  2) sha256(token) → dcm_main.operators(enabled)
//   3) JWT HS256(MIX_JWT_SECRET) → mix 用户(带 uid,用于 user_event 定向)
//   qh 教训: 主判据查 Postgres(无 TTL 悬崖);DB 不可达时 operators 轨降级拒绝(fail-closed),
//   JWT 轨纯本地验签不受影响。
//
// 可观测: 每 5s SET mix:ws:hub_clients=<连接数> EX 15。
// 回滚: mix-ws.service ExecStart 换回 uvicorn app.ws_main:app 即回 Python 版,秒级。

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use sha2::Digest;
use tokio::net::TcpListener;
use tokio::sync::broadcast;
use redis::AsyncCommands;

#[derive(Clone)]
struct Frame {
    target_uid: Option<i64>, // None=广播
    payload: String,
}

struct Hub {
    tx: broadcast::Sender<Frame>,
    clients: DashMap<u64, Option<i64>>, // conn id -> uid(JWT 连接才有)
    next_id: AtomicU64,
}
impl Hub {
    fn new() -> Arc<Self> {
        let (tx, _) = broadcast::channel(2048);
        Arc::new(Hub { tx, clients: DashMap::new(), next_id: AtomicU64::new(1) })
    }
    fn send_all(&self, payload: String) {
        let _ = self.tx.send(Frame { target_uid: None, payload });
    }
    fn send_user(&self, uid: i64, payload: String) {
        let _ = self.tx.send(Frame { target_uid: Some(uid), payload });
    }
}

fn now_ts() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn wrap(alias: &str, raw: &str) -> String {
    let data: serde_json::Value = serde_json::from_str(raw)
        .unwrap_or_else(|_| serde_json::json!({"text": raw}));
    serde_json::json!({"channel": alias, "data": data, "ts": now_ts()}).to_string()
}

/// 订阅四路频道 → 扇出。断线 3s 重连。
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
    pubsub.subscribe("dcm:notify:broadcast").await?;
    pubsub.subscribe("dcm:route:updates").await?;
    pubsub.subscribe("mix:ws:frames").await?;
    pubsub.psubscribe("mix:user:*").await?;
    tracing::info!("subscribed: dcm:notify:broadcast / dcm:route:updates / mix:ws:frames / mix:user:*");
    let mut stream = pubsub.on_message();
    while let Some(msg) = stream.next().await {
        let ch = msg.get_channel_name().to_string();
        let Ok(payload) = msg.get_payload::<String>() else { continue };
        match ch.as_str() {
            "dcm:notify:broadcast" => hub.send_all(wrap("marquee", &payload)),
            "dcm:route:updates" => hub.send_all(wrap("route:updates", &payload)),
            "mix:ws:frames" => hub.send_all(payload), // mix-backend 预打包,透传
            other => {
                if let Some(uid) = other.strip_prefix("mix:user:").and_then(|s| s.parse::<i64>().ok()) {
                    hub.send_user(uid, wrap("user_event", &payload));
                }
            }
        }
    }
    Ok(())
}

/// 每 20s 广播应用层心跳;每 5s 写连接数指标。
async fn heartbeat(hub: Arc<Hub>, url: String) {
    let client = match redis::Client::open(url) { Ok(c) => c, Err(_) => return };
    let mut tick: u64 = 0;
    loop {
        if tick % 4 == 0 {
            hub.send_all(serde_json::json!({"channel":"hb","ts": now_ts()}).to_string());
        }
        if let Ok(mut con) = client.get_multiplexed_async_connection().await {
            let _: Result<(), _> = con.set_ex("mix:ws:hub_clients", hub.clients.len() as i64, 15).await;
        }
        tick += 1;
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

#[derive(serde::Deserialize)]
struct JwtClaims {
    uid: Option<i64>,
    #[allow(dead_code)]
    username: Option<String>,
    #[allow(dead_code)]
    exp: usize,
}

struct Ident {
    uid: Option<i64>,
}

/// 三轨鉴权,与 Python require_viewer 同源。
async fn auth(token: &str, cfg: &Cfg) -> Option<Ident> {
    if token.is_empty() {
        return None;
    }
    // 轨1: 只读令牌
    if !cfg.readonly_token.is_empty() && token == cfg.readonly_token {
        return Some(Ident { uid: None });
    }
    // 轨3(先试,纯本地无 IO): mix 用户 JWT
    if !cfg.jwt_secret.is_empty() {
        let key = jsonwebtoken::DecodingKey::from_secret(cfg.jwt_secret.as_bytes());
        let val = jsonwebtoken::Validation::new(jsonwebtoken::Algorithm::HS256);
        if let Ok(t) = jsonwebtoken::decode::<JwtClaims>(token, &key, &val) {
            return Some(Ident { uid: t.claims.uid });
        }
    }
    // 轨2: operators 表(sha256,查 dcm_main;DB 不可达 fail-closed)
    let hash = hex::encode(sha2::Sha256::digest(token.as_bytes()));
    match tokio_postgres::connect(&cfg.pg_dsn, tokio_postgres::NoTls).await {
        Ok((client, connection)) => {
            let handle = tokio::spawn(async move { let _ = connection.await; });
            let row = client
                .query_opt("SELECT role FROM operators WHERE token_hash=$1 AND enabled", &[&hash])
                .await;
            handle.abort();
            match row {
                Ok(Some(_)) => Some(Ident { uid: None }),
                _ => None,
            }
        }
        Err(e) => {
            tracing::warn!("auth pg connect fail(fail-closed): {e}");
            None
        }
    }
}

#[derive(Clone)]
struct Cfg {
    redis_url: String,
    pg_dsn: String,
    readonly_token: String,
    jwt_secret: String,
}

async fn handle_conn(hub: Arc<Hub>, stream: tokio::net::TcpStream, cfg: Cfg) {
    use tokio_tungstenite::tungstenite::Message;
    // accept_hdr 捕获 URI,取 ?token=
    let mut token = String::new();
    let ws = tokio_tungstenite::accept_hdr_async(stream, |req: &tokio_tungstenite::tungstenite::handshake::server::Request, resp| {
        if let Some(q) = req.uri().query() {
            for kv in q.split('&') {
                if let Some(v) = kv.strip_prefix("token=") {
                    token = urldecode(v);
                }
            }
        }
        Ok(resp)
    }).await;
    let ws = match ws { Ok(w) => w, Err(_) => return };
    let (mut write, mut read) = ws.split();

    let Some(ident) = auth(&token, &cfg).await else {
        let _ = write.send(Message::Text("{\"channel\":\"error\",\"msg\":\"auth failed\"}".into())).await;
        let _ = write.send(Message::Close(None)).await;
        return;
    };

    let id = hub.next_id.fetch_add(1, Ordering::Relaxed);
    let my_uid = ident.uid;
    hub.clients.insert(id, my_uid);
    // 连上立即回一帧 hb,前端 wsOn 秒亮
    let _ = write.send(Message::Text(
        serde_json::json!({"channel":"hb","ts": now_ts()}).to_string())).await;

    let mut rx = hub.tx.subscribe();
    let pump = tokio::spawn(async move {
        while let Ok(f) = rx.recv().await {
            match f.target_uid {
                Some(t) if Some(t) != my_uid => continue, // 定向帧:仅同 uid 收
                _ => {}
            }
            if write.send(Message::Text(f.payload)).await.is_err() {
                break;
            }
        }
    });
    // 上行仅作活性;断开即清理
    while let Some(m) = read.next().await {
        if m.is_err() {
            break;
        }
    }
    pump.abort();
    hub.clients.remove(&id);
}

fn urldecode(s: &str) -> String {
    // token 是 hex/JWT(base64url),仅需处理 %xx 的保守解码
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(b) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(b);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().init();
    let cfg = Cfg {
        redis_url: std::env::var("MIX_REDIS_URL").unwrap_or_else(|_| "redis://10.0.1.212:6379/0".into()),
        pg_dsn: std::env::var("MIX_PG_DSN").unwrap_or_default(),
        readonly_token: std::env::var("MIX_READONLY_TOKEN").unwrap_or_default(),
        jwt_secret: std::env::var("MIX_JWT_SECRET").unwrap_or_default(),
    };
    let bind = std::env::var("MIX_HUB_BIND").unwrap_or_else(|_| "127.0.0.1:8201".into());
    let hub = Hub::new();
    tokio::spawn(redis_subscriber(hub.clone(), cfg.redis_url.clone()));
    tokio::spawn(heartbeat(hub.clone(), cfg.redis_url.clone()));
    let listener = TcpListener::bind(&bind).await.expect("bind");
    tracing::info!("MIX WS HUB listening on {bind} (auth=readonly/operators-pg/jwt)");
    loop {
        if let Ok((stream, _)) = listener.accept().await {
            let (h, c) = (hub.clone(), cfg.clone());
            tokio::spawn(handle_conn(h, stream, c));
        }
    }
}
