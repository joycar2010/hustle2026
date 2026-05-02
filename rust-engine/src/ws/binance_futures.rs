use crate::types::{BinanceCombinedStream, TickerData};
use dashmap::DashMap;
use futures_util::StreamExt;
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

pub async fn run(
    symbols: Vec<String>,
    tickers: Arc<DashMap<String, (TickerData, TickerData)>>,
    update_tx: mpsc::UnboundedSender<String>,
) {
    loop {
        if let Err(e) = connect_and_stream(&symbols, &tickers, &update_tx).await {
            error!(error = %e, "Futures WS disconnected");
        }
        warn!("Futures WS reconnecting in 2s...");
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    }
}

async fn connect_and_stream(
    symbols: &[String],
    tickers: &Arc<DashMap<String, (TickerData, TickerData)>>,
    update_tx: &mpsc::UnboundedSender<String>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let streams: Vec<String> = symbols.iter().map(|s| format!("{}@bookTicker", s)).collect();

    let chunks: Vec<&[String]> = streams.chunks(200).collect();

    let mut handles = Vec::new();

    for chunk in chunks {
        let stream_param = chunk.join("/");
        let url = format!(
            "wss://fstream.binance.com/stream?streams={}",
            stream_param
        );

        let tickers = tickers.clone();
        let update_tx = update_tx.clone();

        let handle = tokio::spawn(async move {
            let (ws, _) = tokio_tungstenite::connect_async(&url).await?;
            info!(streams = chunk.len(), "Futures WS connected");

            let (_, mut read) = ws.split();

            while let Some(msg) = read.next().await {
                let msg = msg?;
                if let tokio_tungstenite::tungstenite::Message::Text(text) = msg {
                    if let Ok(combined) = serde_json::from_str::<BinanceCombinedStream>(&text) {
                        let symbol = combined.data.symbol.clone();
                        let ts = combined.data.timestamp.unwrap_or_else(|| {
                            std::time::SystemTime::now()
                                .duration_since(std::time::UNIX_EPOCH)
                                .unwrap()
                                .as_millis() as i64
                        });

                        let fut = TickerData {
                            bid: combined.data.bid_price,
                            ask: combined.data.ask_price,
                            ts,
                        };

                        tickers
                            .entry(symbol.clone())
                            .and_modify(|pair| pair.1 = fut.clone())
                            .or_insert_with(|| (TickerData::default(), fut));

                        let _ = update_tx.send(symbol);
                    }
                }
            }

            Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
        });
        handles.push(handle);
    }

    for h in handles {
        if let Err(e) = h.await? {
            error!(error = %e, "Futures WS chunk error");
        }
    }

    Ok(())
}
