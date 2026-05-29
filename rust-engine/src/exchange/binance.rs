use crate::tick_store::TickStore;
use futures_util::StreamExt;
use serde::Deserialize;
use std::sync::Arc;
use tokio_tungstenite::connect_async;
use tracing::{error, info, warn};

#[derive(Deserialize)]
struct CombinedMsg {
    data: BookTicker,
}

#[derive(Deserialize)]
struct BookTicker {
    s: String,
    b: String,
    a: String,
}

pub async fn run(url: String, store: Arc<TickStore>) {
    loop {
        info!("[Binance] connecting to {}", &url[..80.min(url.len())]);
        match connect_async(&url).await {
            Ok((ws, _)) => {
                info!("[Binance] connected");
                let (_, mut read) = ws.split();
                while let Some(msg) = read.next().await {
                    match msg {
                        Ok(tokio_tungstenite::tungstenite::Message::Text(txt)) => {
                            if let Ok(cm) = serde_json::from_str::<CombinedMsg>(&txt) {
                                if let (Ok(bid), Ok(ask)) =
                                    (cm.data.b.parse::<f64>(), cm.data.a.parse::<f64>())
                                {
                                    store.update(1, &cm.data.s, bid, ask);
                                }
                            } else if let Ok(bt) = serde_json::from_str::<BookTicker>(&txt) {
                                if let (Ok(bid), Ok(ask)) =
                                    (bt.b.parse::<f64>(), bt.a.parse::<f64>())
                                {
                                    store.update(1, &bt.s, bid, ask);
                                }
                            }
                        }
                        Err(e) => { warn!("[Binance] read error: {e}"); break; }
                        _ => {}
                    }
                }
            }
            Err(e) => error!("[Binance] connect failed: {e}"),
        }
        warn!("[Binance] disconnected, reconnecting in 3s");
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
}
