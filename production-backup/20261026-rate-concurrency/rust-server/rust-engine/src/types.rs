use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default)]
pub struct TickerData {
    pub bid: Decimal,
    pub ask: Decimal,
    /// Exchange event timestamp (used by the engine staleness guard).
    pub ts: i64,
    /// Local receipt timestamp, used by downstream consumers for freshness.
    pub recv_ts: i64,
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
    pub spot_recv_ts_ms: i64,
    pub fut_recv_ts_ms: i64,
}

#[derive(Debug, Deserialize)]
pub struct BinanceBookTicker {
    #[serde(rename = "s")]
    pub symbol: String,
    #[serde(rename = "b", default, with = "rust_decimal::serde::str_option")]
    pub bid_price: Option<Decimal>,
    #[serde(rename = "a", default, with = "rust_decimal::serde::str_option")]
    pub ask_price: Option<Decimal>,
    #[serde(rename = "T")]
    pub timestamp: Option<i64>,
    /// `@ticker` emits once per second; retain `T` for legacy bookTicker.
    #[serde(rename = "E")]
    pub event_time: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct BinanceCombinedStream {
    pub stream: String,
    pub data: BinanceBookTicker,
}

#[cfg(test)]
mod tests {
    use super::BinanceCombinedStream;

    #[test]
    fn deserializes_ticker_best_bid_ask_and_event_time() {
        let frame = r#"{"stream":"ontusdt@ticker","data":{"e":"24hrTicker","E":1710000000123,"s":"ONTUSDT","b":"0.3120","B":"10","a":"0.3130","A":"12","T":1710000000000}}"#;
        let parsed: BinanceCombinedStream = serde_json::from_str(frame).expect("ticker frame");
        assert_eq!(parsed.data.symbol, "ONTUSDT");
        assert_eq!(parsed.data.event_time, Some(1710000000123));
        assert_eq!(parsed.data.timestamp, Some(1710000000000));
        assert_eq!(parsed.data.bid_price.unwrap().to_string(), "0.3120");
    }
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
