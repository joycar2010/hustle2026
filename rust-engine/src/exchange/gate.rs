use crate::tick_store::TickStore;
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use std::sync::Arc;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{error, info, warn};

#[derive(Deserialize)]
struct GateMsg {
    channel: Option<String>,
    event: Option<String>,
    result: Option<Vec<GateTick>>,
}

#[derive(Deserialize)]
struct GateTick {
    contract: String,
    #[serde(default)]
    highest_bid: Option<String>,
    #[serde(default)]
    lowest_ask: Option<String>,
    #[serde(default)]
    mark_price: Option<String>,
}

pub async fn run(symbols: Vec<String>, store: Arc<TickStore>) {
    let url = "wss://fx-ws.gateio.ws/v4/ws/usdt";
    loop {
        info!("[Gate] connecting, {} symbols", symbols.len());
        match connect_async(url).await {
            Ok((ws, _)) => {
                let (mut write, mut read) = ws.split();
                let sub = serde_json::json!({
                    "time": chrono_ts(),
                    "channel": "futures.tickers",
                    "event": "subscribe",
                    "payload": symbols
                });
                if let Err(e) = write.send(Message::Text(sub.to_string().into())).await {
                    error!("[Gate] subscribe failed: {e}");
                    continue;
                }
                info!("[Gate] subscribed");

                let ping_handle = tokio::spawn({
                    let mut w = write;
                    async move {
                        loop {
                            tokio::time::sleep(std::time::Duration::from_secs(15)).await;
                            let ping = serde_json::json!({"channel": "futures.ping"});
                            if w.send(Message::Text(ping.to_string().into())).await.is_err() {
                                break;
                            }
                        }
                    }
                });

                while let Some(msg) = read.next().await {
                    match msg {
                        Ok(Message::Text(txt)) => {
                            if let Ok(m) = serde_json::from_str::<GateMsg>(&txt) {
                                if m.channel.as_deref() == Some("futures.tickers")
                                    && m.event.as_deref() == Some("update")
                                {
                                    if let Some(results) = m.result {
                                        for t in results {
                                            let bid = t.highest_bid.as_deref()
                                                .and_then(|s| s.parse::<f64>().ok());
                                            let ask = t.lowest_ask.as_deref()
                                                .and_then(|s| s.parse::<f64>().ok());
                                            let (bid, ask) = match (bid, ask) {
                                                (Some(b), Some(a)) if b > 0.0 && a > 0.0 => (b, a),
                                                _ => {
                                                    if let Some(mp) = t.mark_price.as_deref()
                                                        .and_then(|s| s.parse::<f64>().ok())
                                                    {
                                                        (mp - 0.01, mp + 0.01)
                                                    } else {
                                                        continue;
                                                    }
                                                }
                                            };
                                            store.update(4, &t.contract, bid, ask);
                                        }
                                    }
                                }
                            }
                        }
                        Err(e) => { warn!("[Gate] read error: {e}"); break; }
                        _ => {}
                    }
                }
                ping_handle.abort();
            }
            Err(e) => error!("[Gate] connect failed: {e}"),
        }
        warn!("[Gate] disconnected, reconnecting in 3s");
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
}

fn chrono_ts() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
}
