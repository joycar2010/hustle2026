use crate::types::{SpreadSnapshot, TickerData};
use rust_decimal::Decimal;

const HUNDRED: Decimal = Decimal::ONE_HUNDRED;

pub fn calculate(symbol: &str, spot: &TickerData, futures: &TickerData) -> Option<SpreadSnapshot> {
    if spot.ask.is_zero() || futures.ask.is_zero() || spot.bid.is_zero() || futures.bid.is_zero() {
        return None;
    }

    // 做多(期多): 做多合约 + 做空现货 = (fut_bid - spot_ask) / spot_ask * 100
    let spread_long = (futures.bid - spot.ask) / spot.ask * HUNDRED;

    // 做空(期空): 做空合约 + 做多现货 = (spot_bid - fut_ask) / fut_ask * 100
    let spread_short = (spot.bid - futures.ask) / futures.ask * HUNDRED;

    let ts = spot.ts.max(futures.ts);

    Some(SpreadSnapshot {
        symbol: symbol.to_string(),
        spot_bid: spot.bid,
        spot_ask: spot.ask,
        fut_bid: futures.bid,
        fut_ask: futures.ask,
        spread_long,
        spread_short,
        ts,
        // Keep exchange event time for display/diagnostics, but propagate the
        // per-leg local receipt times for every downstream execution guard.
        spot_recv_ts_ms: spot.recv_ts,
        fut_recv_ts_ms: futures.recv_ts,
    })
}

#[cfg(test)]
mod tests {
    use super::calculate;
    use crate::types::TickerData;
    use rust_decimal::Decimal;

    fn ticker(bid: &str, ask: &str, ts: i64, recv_ts: i64) -> TickerData {
        TickerData {
            bid: bid.parse::<Decimal>().unwrap(),
            ask: ask.parse::<Decimal>().unwrap(),
            ts,
            recv_ts,
        }
    }

    #[test]
    fn propagates_local_receive_timestamps_per_leg() {
        let spot = ticker("1", "1.01", 100, 1_000);
        let futures = ticker("1.02", "1.03", 200, 2_000);
        let snapshot = calculate("TESTUSDT", &spot, &futures).expect("valid quote");

        assert_eq!(snapshot.ts, 200);
        assert_eq!(snapshot.spot_recv_ts_ms, 1_000);
        assert_eq!(snapshot.fut_recv_ts_ms, 2_000);
    }
}
