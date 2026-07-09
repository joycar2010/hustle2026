use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};

/// venue 无关的归一化 L1 盘口。ts=交易所事件时间(缺失则收帧本地时间),recv_ts=收帧本地时间。
/// 数据面只采集归一不判断:新鲜度/冻结判定交给下游消费者(引擎/采样器)按各自口径做。
#[derive(Debug, Clone, Default)]
pub struct TickerData {
    pub bid: Decimal,
    pub ask: Decimal,
    pub bid_sz: Decimal,
    pub ask_sz: Decimal,
    pub ts: i64,
    pub recv_ts: i64,
}

/// 发布到 Redis 的快照(HSET dcm:feed:{venue}:{market} field=SYMBOL)。
#[derive(Debug, Clone, Serialize)]
pub struct TickerSnapshot<'a> {
    pub venue: &'a str,
    pub market: &'a str,
    pub symbol: &'a str,
    pub bid: Decimal,
    pub ask: Decimal,
    pub bid_sz: Decimal,
    pub ask_sz: Decimal,
    pub ts: i64,
    pub recv_ts: i64,
}

/// 币安 bookTicker(spot 无事件时间 T,usdm 有;B/A=一档量)。
#[derive(Debug, Deserialize)]
pub struct BinanceBookTicker {
    #[serde(rename = "s")]
    pub symbol: String,
    #[serde(rename = "b", with = "rust_decimal::serde::str")]
    pub bid_price: Decimal,
    #[serde(rename = "B", with = "rust_decimal::serde::str")]
    pub bid_qty: Decimal,
    #[serde(rename = "a", with = "rust_decimal::serde::str")]
    pub ask_price: Decimal,
    #[serde(rename = "A", with = "rust_decimal::serde::str")]
    pub ask_qty: Decimal,
    #[serde(rename = "T")]
    pub timestamp: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct BinanceCombinedStream {
    #[allow(dead_code)]
    pub stream: String,
    pub data: BinanceBookTicker,
}
