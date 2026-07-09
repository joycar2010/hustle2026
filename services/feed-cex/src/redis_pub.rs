use crate::types::TickerSnapshot;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::error;

/// 键空间契约(与 coin 的 spreads/engine:* 完全隔离):
/// - HSET dcm:feed:{venue}:{market} <SYMBOL> <json>  + PUBLISH dcm:feed:updates "{venue}:{market}:{SYMBOL}"
/// - SET  dcm:hb:feed-cex <json> EX 90   (吞吐计数即心跳,风控面/看门狗按 dcm:hb:* 巡检)
pub struct RedisPublisher {
    conn: Arc<Mutex<redis::aio::ConnectionManager>>,
}

impl RedisPublisher {
    pub async fn new(redis_url: &str) -> Result<Self, redis::RedisError> {
        let client = redis::Client::open(redis_url)?;
        let conn = client.get_connection_manager().await?;
        Ok(Self { conn: Arc::new(Mutex::new(conn)) })
    }

    pub async fn publish_ticker(&self, snap: &TickerSnapshot<'_>) {
        let json = match serde_json::to_string(snap) {
            Ok(j) => j,
            Err(e) => {
                error!(error = %e, "serialize ticker failed");
                return;
            }
        };
        let hash_key = format!("dcm:feed:{}:{}", snap.venue, snap.market);
        let chan_field = format!("{}:{}:{}", snap.venue, snap.market, snap.symbol);
        let mut conn = self.conn.lock().await;
        let r: Result<(), redis::RedisError> = redis::pipe()
            .hset(&hash_key, snap.symbol, &json)
            .publish("dcm:feed:updates", &chan_field)
            .query_async(&mut *conn)
            .await;
        if let Err(e) = r {
            error!(error = %e, key = %chan_field, "redis write failed");
        }
    }

    pub async fn set_heartbeat(&self, json: &str) {
        let mut conn = self.conn.lock().await;
        let r: Result<(), redis::RedisError> = redis::cmd("SET")
            .arg("dcm:hb:feed-cex")
            .arg(json)
            .arg("EX")
            .arg(90)
            .query_async(&mut *conn)
            .await;
        if let Err(e) = r {
            error!(error = %e, "redis heartbeat write failed");
        }
    }
}
