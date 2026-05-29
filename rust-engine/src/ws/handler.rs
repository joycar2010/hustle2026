use axum::{
    extract::{ws::{Message, WebSocket, WebSocketUpgrade}, Query, State},
    response::IntoResponse,
};
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;
use tracing::{info, warn};

use crate::ws::auth;
use crate::ws::hub::Hub;
use crate::config::AppConfig;

#[derive(Deserialize)]
pub struct WsParams {
    token: Option<String>,
}

pub struct WsState {
    pub hub: Arc<Hub>,
    pub config: AppConfig,
}

pub async fn ws_handler(
    ws: WebSocketUpgrade,
    Query(params): Query<WsParams>,
    State(state): State<Arc<WsState>>,
) -> impl IntoResponse {
    let token = params.token.unwrap_or_default();
    match auth::validate_token(&token, &state.config.secret_key) {
        Ok(user_id) => ws.on_upgrade(move |socket| handle_socket(socket, user_id, state)),
        Err(e) => {
            warn!("[WS] auth failed: {e}");
            axum::http::StatusCode::UNAUTHORIZED.into_response()
        }
    }
}

async fn handle_socket(socket: WebSocket, user_id: String, state: Arc<WsState>) {
    let (mut ws_tx, mut ws_rx) = socket.split();
    let (tx, mut rx) = mpsc::unbounded_channel::<String>();

    let client_id = state.hub.register(user_id.clone(), tx);

    let welcome = serde_json::json!({
        "type": "connection",
        "message": "Connected to Hustle Arbitrage System",
        "user_id": &user_id,
        "service": "rust-engine",
        "timestamp": now_ms(),
    });
    let _ = ws_tx.send(Message::Text(welcome.to_string().into())).await;

    let write_task = tokio::spawn(async move {
        let mut ping_interval = tokio::time::interval(Duration::from_secs(30));
        ping_interval.tick().await;
        loop {
            tokio::select! {
                Some(msg) = rx.recv() => {
                    if ws_tx.send(Message::Text(msg.into())).await.is_err() {
                        break;
                    }
                }
                _ = ping_interval.tick() => {
                    if ws_tx.send(Message::Ping(vec![].into())).await.is_err() {
                        break;
                    }
                }
            }
        }
    });

    let hub = state.hub.clone();
    let read_task = tokio::spawn(async move {
        while let Some(Ok(msg)) = ws_rx.next().await {
            match msg {
                Message::Text(txt) => {
                    if let Ok(cmd) = serde_json::from_str::<serde_json::Value>(&txt) {
                        match cmd.get("type").and_then(|v| v.as_str()) {
                            Some("subscribe") => {
                                if let Some(pairs) = cmd.get("pairs").and_then(|v| v.as_array()) {
                                    for p in pairs {
                                        if let Some(pc) = p.as_str() {
                                            hub.subscribe(client_id, pc);
                                        }
                                    }
                                }
                            }
                            Some("unsubscribe") => {
                                if let Some(pairs) = cmd.get("pairs").and_then(|v| v.as_array()) {
                                    for p in pairs {
                                        if let Some(pc) = p.as_str() {
                                            hub.unsubscribe(client_id, pc);
                                        }
                                    }
                                }
                            }
                            Some("request_snapshot") => {
                                info!("[WS] snapshot requested by client {client_id}");
                            }
                            _ => {}
                        }
                    }
                }
                Message::Pong(_) => {}
                Message::Close(_) => break,
                _ => {}
            }
        }
    });

    tokio::select! {
        _ = write_task => {}
        _ = read_task => {}
    }

    state.hub.unregister(client_id);
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as i64
}
