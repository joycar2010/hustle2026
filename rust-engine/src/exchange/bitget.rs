use crate::tick_store::TickStore;
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use std::sync::Arc;
use tokio_tungstenite::{connect_async, tungstenite::Message};
use tracing::{error, info, warn};

#[derive(Deserialize)]
struct BitgetMsg {
    data: Option<Vec<BitgetTick>>,
}

#[derive(Deserialize)]
struct BitgetTick {
    #[serde(rename = "instId")]
    inst_id: String,
    #[serde(rename = "bidPr")]
    bid_pr: String,
    #[serde(rename = "askPr")]
    ask_pr: String,
}

pub async fn run(symbols: Vec<String>, store: Arc<TickStore>) {
    let url = "wss://ws.bitget.com/v2/ws/public";
    loop {
        info!("[Bitget] connecting, {} symbols", symbols.len());
        match connect_async(url).await {
            Ok((ws, _)) => {
                let (mut write, mut read) = ws.split();
                let args: Vec<serde_json::Value> = symbols
                    .iter()
                    .map(|s| serde_json::json!({
                        "instType": "USDT-FUTURES",
                        "channel": "ticker",
                        "instId": s
                    }))
                    .collect();
                let sub = serde_json::json!({"op": "subscribe", "args": args});
                if let Err(e) = write.send(Message::Text(sub.to_string().into())).await {
                    error!("[Bitget] subscribe failed: {e}");
                    continue;
                }
                info!("[Bitget] subscribed");

                let ping_handle = tokio::spawn({
                    let mut w = write;
                    async move {
                        loop {
                            tokio::time::sleep(std::time::Duration::from_secs(25)).await;
                            if w.send(Message::Text("ping".to_string().into())).await.is_err() {
                                break;
                            }
                        }
                    }
                });

                while let Some(msg) = read.next().await {
                    match msg {
                        Ok(Message::Text(txt)) => {
                            if txt == "pong" { continue; }
                            if let Ok(m) = serde_json::from_str::<BitgetMsg>(&txt) {
                                if let Some(data) = m.data {
                                    for t in data {
                                        if let (Ok(bid), Ok(ask)) =
                                            (t.bid_pr.parse::<f64>(), t.ask_pr.parse::<f64>())
                                        {
                                            store.update(6, &t.inst_id, bid, ask);
                                        }
                                    }
                                }
                            }
                        }
                        Err(e) => { warn!("[Bitget] read error: {e}"); break; }
                        _ => {}
                    }
                }
                ping_handle.abort();
            }
            Err(e) => error!("[Bitget] connect failed: {e}"),
        }
        warn!("[Bitget] disconnected, reconnecting in 3s");
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
}
