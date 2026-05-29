use dashmap::DashMap;
use std::collections::HashSet;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::info;

pub type WsSender = mpsc::UnboundedSender<String>;

struct ClientState {
    tx: WsSender,
    user_id: String,
    rooms: HashSet<String>,
}

pub struct Hub {
    clients: DashMap<u64, ClientState>,
    next_id: AtomicU64,
}

impl Hub {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            clients: DashMap::new(),
            next_id: AtomicU64::new(1),
        })
    }

    pub fn register(&self, user_id: String, tx: WsSender) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        self.clients.insert(id, ClientState {
            tx,
            user_id: user_id.clone(),
            rooms: HashSet::new(),
        });
        info!("[Hub] user={user_id} connected (id={id}), total={}", self.clients.len());
        id
    }

    pub fn unregister(&self, id: u64) {
        if let Some((_, st)) = self.clients.remove(&id) {
            info!("[Hub] user={} disconnected (id={id}), total={}", st.user_id, self.clients.len());
        }
    }

    pub fn subscribe(&self, client_id: u64, pair_code: &str) {
        if let Some(mut st) = self.clients.get_mut(&client_id) {
            st.rooms.insert(pair_code.to_string());
            info!("[Hub] client {client_id} subscribed to {pair_code}");
        }
    }

    pub fn unsubscribe(&self, client_id: u64, pair_code: &str) {
        if let Some(mut st) = self.clients.get_mut(&client_id) {
            st.rooms.remove(pair_code);
        }
    }

    pub fn broadcast(&self, msg: &str) {
        for entry in self.clients.iter() {
            let _ = entry.value().tx.send(msg.to_string());
        }
    }

    pub fn broadcast_to_room(&self, pair_code: &str, msg: &str) {
        for entry in self.clients.iter() {
            if entry.value().rooms.contains(pair_code) {
                let _ = entry.value().tx.send(msg.to_string());
            }
        }
    }

    pub fn send_to_user(&self, user_id: &str, msg: &str) {
        for entry in self.clients.iter() {
            if entry.value().user_id == user_id {
                let _ = entry.value().tx.send(msg.to_string());
            }
        }
    }

    pub fn client_count(&self) -> usize {
        self.clients.len()
    }
}
