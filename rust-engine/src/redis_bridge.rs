use crate::ws::hub::Hub;
use futures_util::StreamExt;
use std::sync::Arc;
use tracing::{error, info, warn};

const CHANNELS: &[&str] = &[
    "ws:broadcast",
    "ws:market_data",
    "ws:account_balance",
    "ws:risk_metrics",
    "ws:order_update",
    "ws:position_update",
    "ws:user_event",
    "ws:mt5_connection_status",
    "ws:stream",
];

pub async fn run(redis_url: String, hub: Arc<Hub>) {
    loop {
        if let Err(e) = subscribe_loop(&redis_url, &hub).await {
            error!("[RedisBridge] error: {e}, retrying in 3s");
        }
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
}

async fn subscribe_loop(redis_url: &str, hub: &Arc<Hub>) -> Result<(), Box<dyn std::error::Error>> {
    let client = redis::Client::open(redis_url)?;
    let mut pubsub = client.get_async_pubsub().await?;
    for ch in CHANNELS {
        pubsub.subscribe(*ch).await?;
    }
    info!("[RedisBridge] subscribed to {} channels", CHANNELS.len());

    let mut stream = pubsub.on_message();
    while let Some(msg) = stream.next().await {
        let channel: String = msg.get_channel().unwrap_or_default();
        let payload: String = match msg.get_payload() {
            Ok(p) => p,
            Err(_) => continue,
        };

        let parsed: serde_json::Value = match serde_json::from_str(&payload) {
            Ok(v) => v,
            Err(_) => {
                warn!("[RedisBridge] invalid JSON on {channel}");
                continue;
            }
        };

        // ws:stream — Python stream_hub bridge.
        // Payload: { channel: "site.status", payload: {...} }
        // Forward as Python protocol: { type: "stream", channel, payload }
        // so frontends listening for `{type:"stream", channel, payload}` work.
        if channel == "ws:stream" {
            let stream_channel = parsed.get("channel").and_then(|v| v.as_str()).unwrap_or("");
            let stream_payload = parsed.get("payload").unwrap_or(&serde_json::Value::Null);
            if !stream_channel.is_empty() {
                let out = serde_json::json!({
                    "type": "stream",
                    "channel": stream_channel,
                    "payload": stream_payload,
                });
                // Per-user channels: route to specific user, else broadcast
                if stream_channel.starts_with("user.") || stream_channel.starts_with("alerts.") {
                    if let Some(user_suffix) = stream_channel.rsplit('.').next() {
                        if user_suffix != "global" {
                            hub.send_to_user(user_suffix, &out.to_string());
                            continue;
                        }
                    }
                }
                hub.broadcast(&out.to_string());
            }
            continue;
        }

        if channel == "ws:user_event" {
            let user_id = parsed.get("user_id").and_then(|v| v.as_str()).unwrap_or("");
            let evt_type = parsed.get("type").and_then(|v| v.as_str()).unwrap_or("event");
            let data = parsed.get("data").unwrap_or(&parsed);
            if !user_id.is_empty() {
                let out = serde_json::json!({
                    "type": evt_type,
                    "data": data,
                    "timestamp": now_ms(),
                });
                hub.send_to_user(user_id, &out.to_string());
            }
            continue;
        }

        let msg_type = parsed
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or_else(|| match channel.as_str() {
                "ws:market_data" => "market_data",
                "ws:account_balance" => "account_balance",
                "ws:risk_metrics" => "risk_metrics",
                "ws:order_update" => "order_update",
                "ws:position_update" => "position_update",
                _ => "event",
            });

        let data = parsed.get("data").unwrap_or(&parsed);
        let out = serde_json::json!({
            "type": msg_type,
            "data": data,
            "timestamp": now_ms(),
        });
        let out_str = out.to_string();

        if channel == "ws:market_data" {
            if let Some(pc) = parsed.get("pair_code").and_then(|v| v.as_str()) {
                hub.broadcast_to_room(pc, &out_str);
                continue;
            }
        }

        hub.broadcast(&out_str);
    }

    Ok(())
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64
}
