use crate::types::{SpreadSnapshot, TickerData};
use rust_decimal::Decimal;
use rust_decimal::prelude::Zero;

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
    })
}
