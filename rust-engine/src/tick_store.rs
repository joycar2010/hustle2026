use dashmap::DashMap;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug)]
pub struct TickData {
    pub bid: f64,
    pub ask: f64,
    pub timestamp: i64,
}

pub struct TickStore {
    ticks: DashMap<String, TickData>,
}

impl TickStore {
    pub fn new() -> Self {
        Self { ticks: DashMap::new() }
    }

    fn key(platform_id: u32, symbol: &str) -> String {
        format!("{}:{}", platform_id, symbol.to_lowercase())
    }

    pub fn update(&self, platform_id: u32, symbol: &str, bid: f64, ask: f64) {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as i64;
        self.ticks.insert(
            Self::key(platform_id, symbol),
            TickData { bid, ask, timestamp: ts },
        );
    }

    pub fn get(&self, platform_id: u32, symbol: &str) -> Option<TickData> {
        self.ticks.get(&Self::key(platform_id, symbol)).map(|r| r.clone())
    }

    pub fn tick_count(&self) -> usize {
        self.ticks.len()
    }
}
