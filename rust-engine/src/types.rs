use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default)]
pub struct TickerData {
    pub bid: Decimal,
    pub ask: Decimal,
    pub ts: i64,
}

#[derive(Debug, Clone, Default)]
pub struct TickerPair {
    pub symbol: String,
    pub spot: TickerData,
    pub futures: TickerData,
}

#[derive(Debug, Clone, Serialize)]
pub struct SpreadSnapshot {
    pub symbol: String,
    pub spot_bid: Decimal,
    pub spot_ask: Decimal,
    pub fut_bid: Decimal,
    pub fut_ask: Decimal,
    pub spread_long: Decimal,
    pub spread_short: Decimal,
    pub ts: i64,
}

#[derive(Debug, Deserialize)]
pub struct BinanceBookTicker {
    #[serde(rename = "s")]
    pub symbol: String,
    #[serde(rename = "b", with = "rust_decimal::serde::str")]
    pub bid_price: Decimal,
    #[serde(rename = "a", with = "rust_decimal::serde::str")]
    pub ask_price: Decimal,
    #[serde(rename = "T")]
    pub timestamp: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct BinanceCombinedStream {
    pub stream: String,
    pub data: BinanceBookTicker,
}

#[derive(Debug, Clone)]
pub struct LatencyStats {
    pub count: u64,
    pub sum_us: u64,
    pub max_us: u64,
    pub p99_samples: Vec<u64>,
}

impl LatencyStats {
    pub fn new() -> Self {
        Self {
            count: 0,
            sum_us: 0,
            max_us: 0,
            p99_samples: Vec::with_capacity(10000),
        }
    }

    pub fn record(&mut self, us: u64) {
        self.count += 1;
        self.sum_us += us;
        if us > self.max_us {
            self.max_us = us;
        }
        self.p99_samples.push(us);
    }

    pub fn report_and_reset(&mut self) -> (f64, u64, u64) {
        if self.count == 0 {
            return (0.0, 0, 0);
        }
        let avg = self.sum_us as f64 / self.count as f64;
        let p99 = if !self.p99_samples.is_empty() {
            let mut sorted = self.p99_samples.clone();
            sorted.sort_unstable();
            let idx = (sorted.len() as f64 * 0.99) as usize;
            sorted[idx.min(sorted.len() - 1)]
        } else {
            0
        };
        let max = self.max_us;
        *self = Self::new();
        (avg, p99, max)
    }
}
