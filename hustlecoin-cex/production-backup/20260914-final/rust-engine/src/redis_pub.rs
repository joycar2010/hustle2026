use crate::config::{EXECUTION_UNIVERSE_KEY, EXIT_UNIVERSE_KEY};
use crate::types::SpreadSnapshot;
use serde_json::Value;
use std::collections::HashSet;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{error, info};

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

    /// Publish only the latest snapshot for each symbol in one Redis
    /// pipeline. The WS feeds can emit thousands of updates per second; a
    /// per-message round trip lets the processor backlog and makes quiet
    /// symbols appear stale even while their sockets are healthy.
    pub async fn publish_spreads(&self, snapshots: &[SpreadSnapshot]) {
        if snapshots.is_empty() {
            return;
        }
        let mut pipe = redis::pipe();
        let mut count = 0usize;
        for snapshot in snapshots {
            let Ok(json) = serde_json::to_string(snapshot) else {
                error!(symbol = %snapshot.symbol, "Failed to serialize spread");
                continue;
            };
            pipe.hset("spreads", &snapshot.symbol, json)
                .publish("spread:updates", &snapshot.symbol);
            count += 1;
        }
        if count == 0 {
            return;
        }
        let mut conn = self.conn.lock().await;
        let result: Result<(), redis::RedisError> = pipe.query_async(&mut *conn).await;
        if let Err(e) = result {
            error!(error = %e, count, "Redis batch write failed");
        }
    }

    /// 把 30s 吞吐/护栏计数写到 Redis,供 python 巡检读取(SET engine:throughput, 90s 过期)。
    pub async fn set_throughput(&self, json: &str) {
        let mut conn = self.conn.lock().await;
        let r: Result<(), redis::RedisError> = redis::cmd("SET")
            .arg("engine:throughput")
            .arg(json)
            .arg("EX")
            .arg(90)
            .query_async(&mut *conn)
            .await;
        if let Err(e) = r {
            error!(error = %e, "Redis throughput write failed");
        }
    }

    /// Remove retired symbols and snapshots that have not been refreshed for
    /// the retention window. The spread hash is otherwise append-only, so a
    /// delisted/quiet symbol can remain visible indefinitely after publishing
    /// has correctly stopped.
    pub async fn prune_stale_spreads(&self, now_ms: i64, max_age_ms: i64) {
        let mut conn = self.conn.lock().await;
        let rows: Result<Vec<(String, String)>, redis::RedisError> = redis::cmd("HGETALL")
            .arg("spreads")
            .query_async(&mut *conn)
            .await;
        let rows = match rows {
            Ok(rows) => rows,
            Err(error) => {
                error!(%error, "Redis spread prune read failed");
                return;
            }
        };

        // A delisted symbol can disappear from the execution universe while
        // an active Position still owns an exit-only lease.  Retain snapshots
        // for the union, but fail closed on either Redis read/JSON payload so
        // a transient control-plane error cannot delete live exit quotes.
        let execution_raw: Result<Option<String>, redis::RedisError> = redis::cmd("GET")
            .arg(EXECUTION_UNIVERSE_KEY)
            .query_async(&mut *conn)
            .await;
        let exit_raw: Result<Option<String>, redis::RedisError> = redis::cmd("GET")
            .arg(EXIT_UNIVERSE_KEY)
            .query_async(&mut *conn)
            .await;
        let universe: Option<HashSet<String>> = match (execution_raw, exit_raw) {
            // A missing key is an unavailable control-plane snapshot, not an
            // authoritative empty universe.  Retain recent snapshots until a
            // complete execution+exit pair is available again.
            (Ok(Some(execution)), Ok(Some(exit_only))) => {
                match (
                    serde_json::from_str::<Vec<String>>(&execution),
                    serde_json::from_str::<Vec<String>>(&exit_only),
                ) {
                    (Ok(execution), Ok(exit_only)) => Some(
                        execution
                            .into_iter()
                            .chain(exit_only)
                            .map(|symbol| symbol.to_uppercase())
                            .collect(),
                    ),
                    _ => {
                        error!("Redis universe JSON malformed during spread prune");
                        None
                    }
                }
            }
            (Ok(_), Ok(_)) => None,
            (Err(error), _) | (_, Err(error)) => {
                error!(%error, "Redis universe read failed during spread prune");
                None
            }
        };

        let mut remove = Vec::new();
        for (symbol, raw) in rows {
            let retired = universe
                .as_ref()
                .is_some_and(|allowed| !allowed.contains(&symbol.to_uppercase()));
            let stale = serde_json::from_str::<Value>(&raw)
                .ok()
                .map(|value| {
                    let spot = value
                        .get("spot_recv_ts_ms")
                        .and_then(Value::as_i64)
                        .unwrap_or(0);
                    let futures = value
                        .get("fut_recv_ts_ms")
                        .and_then(Value::as_i64)
                        .unwrap_or(0);
                    spot <= 0
                        || futures <= 0
                        || now_ms.saturating_sub(spot.min(futures)) > max_age_ms
                })
                .unwrap_or(true);
            if retired || stale {
                remove.push(symbol);
            }
        }

        if remove.is_empty() {
            return;
        }
        let mut pipe = redis::pipe();
        for symbol in &remove {
            pipe.hdel("spreads", symbol);
        }
        if let Err(error) = pipe.query_async::<()>(&mut *conn).await {
            error!(%error, count = remove.len(), "Redis spread prune delete failed");
            return;
        }
        info!(removed = remove.len(), "Pruned retired/stale spread snapshots");
    }
}
