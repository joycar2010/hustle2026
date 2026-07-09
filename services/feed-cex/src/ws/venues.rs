//! VenueSpec 表:每个 (venue, market) 一条规格,泛型连接器按规格工作。
//! 新增一所 = 新增一条 spec(url/subscribe/parse/ping 四件套),连接器骨架零改动。

use crate::types::{BinanceCombinedStream, TickerData};

/// 保活模式:币安走协议层 Ping/Pong(服务器发 Ping 我们回 Pong);
/// OKX 等需要客户端周期发文本 ping(如 "ping"),服务器回文本 "pong"。
#[derive(Debug, Clone, Copy)]
pub enum PingMode {
    Protocol,
    #[allow(dead_code)] // OKX/Bybit 接入时启用
    Text { payload: &'static str, every_secs: u64 },
}

#[derive(Clone, Copy)]
pub struct VenueSpec {
    pub venue: &'static str,
    pub market: &'static str,
    /// 单连接最大订阅流数(币安 combined stream 上限内取 200,沿 coin 实测值)。
    pub max_streams_per_conn: usize,
    /// 由一个 chunk 的小写 symbol 列表构造连接 URL。
    pub url: fn(&[String]) -> String,
    /// 连接后需要发送的订阅消息(币安 URL 内订阅=空;OKX/Bybit 走消息订阅)。
    pub subscribe: fn(&[String]) -> Vec<String>,
    /// 解析一帧文本 → (大写SYMBOL, ticker)。非行情帧(订阅ack/pong)返回 None。
    pub parse: fn(&str, i64) -> Option<(String, TickerData)>,
    pub ping: PingMode,
}

impl VenueSpec {
    pub fn key(&self) -> String {
        format!("{}_{}", self.venue, self.market)
    }
}

fn binance_parse(text: &str, recv_ts: i64) -> Option<(String, TickerData)> {
    let combined: BinanceCombinedStream = serde_json::from_str(text).ok()?;
    let d = combined.data;
    Some((
        d.symbol,
        TickerData {
            bid: d.bid_price,
            ask: d.ask_price,
            bid_sz: d.bid_qty,
            ask_sz: d.ask_qty,
            // spot bookTicker 无事件时间 T → 用收帧本地时间(与 coin 同语义)
            ts: d.timestamp.unwrap_or(recv_ts),
            recv_ts,
        },
    ))
}

fn binance_streams(symbols: &[String]) -> String {
    symbols
        .iter()
        .map(|s| format!("{s}@bookTicker"))
        .collect::<Vec<_>>()
        .join("/")
}

pub const BINANCE_SPOT: VenueSpec = VenueSpec {
    venue: "binance",
    market: "spot",
    max_streams_per_conn: 200,
    url: |syms| format!("wss://stream.binance.com:9443/stream?streams={}", binance_streams(syms)),
    subscribe: |_| Vec::new(),
    parse: binance_parse,
    ping: PingMode::Protocol,
};

pub const BINANCE_USDM: VenueSpec = VenueSpec {
    venue: "binance",
    market: "usdm",
    max_streams_per_conn: 200,
    url: |syms| format!("wss://fstream.binance.com/stream?streams={}", binance_streams(syms)),
    subscribe: |_| Vec::new(),
    parse: binance_parse,
    ping: PingMode::Protocol,
};

/// 已注册的全部 spec;按 DCM_FEED_VENUES(逗号分隔的 spec.key)筛选启用。
pub const ALL_SPECS: &[VenueSpec] = &[BINANCE_SPOT, BINANCE_USDM];
