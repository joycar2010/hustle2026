use crate::types::SpreadSnapshot;
use redis::AsyncCommands;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::error;

pub struct RedisPublisher {
    conn: Arc<Mutex<redis::aio::ConnectionManager>>,
}

impl RedisPublisher {
    pub async fn new(redis_url: &str) -> Result<Self, redis::RedisError> {
        let client = redis::Client::open(redis_url)?;
        let conn = client.get_connection_manager().await?;
        Ok(Self {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub async fn publish_spread(&self, snapshot: &SpreadSnapshot) {
        let json = match serde_json::to_string(snapshot) {
            Ok(j) => j,
            Err(e) => {
                error!(error = %e, "Failed to serialize spread");
                return;
            }
        };

        let mut conn = self.conn.lock().await;

        let result: Result<(), redis::RedisError> = redis::pipe()
            .hset("spreads", &snapshot.symbol, &json)
            .publish("spread:updates", &snapshot.symbol)
            .query_async(&mut *conn)
            .await;

        if let Err(e) = result {
            error!(error = %e, symbol = %snapshot.symbol, "Redis write failed");
        }
    }
}
