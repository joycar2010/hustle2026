//! VenueSpec 表:每个 (venue, market) 一条规格,泛型连接器按规格工作。
//! 新增一所 = 一条 spec(url/subscribe/parse/ping/normalize 五件套),连接器骨架零改动。
//!
//! 符号约定:
//! - universe(Redis dcm:feed:universe:{venue}[:{market}])存 **venue 原生格式**(订阅要用);
//! - 发布/共享表键一律 **统一符号** = spec.normalize(原生),大写无分隔符(BTCUSDT),跨所可 join;
//! - 兜底宇宙存 base(btc/eth/...),spec.to_native 映射回原生。
//!
//! 保活:币安=协议 Ping/Pong;OKX/Bitget=裸文本"ping";Bybit={"op":"ping"};Gate=带时间戳 ping 帧。
//! 新鲜度阈值 per-spec:小所长尾币静默期长,先保守(900s/60%),跑一周用长窗口停更比例实测再校准
//! (coin 教训:阈值拍脑袋=狂误报重连或半开漏报)。

use crate::types::{BinanceCombinedStream, ParsedTick};
use rust_decimal::Decimal;
use serde_json::Value;
use std::str::FromStr;

#[derive(Clone, Copy)]
pub enum PingMode {
    Protocol,
    Text { build: fn() -> String, every_secs: u64 },
}

/// TLS 栈选择:默认 Rustls;Gate 前置层按 TLS 指纹(JA3)掐 rustls 握手 → 走 NativeTls(OpenSSL)。
#[derive(Clone, Copy, Debug)]
pub enum TlsMode {
    Rustls,
    NativeTls,
}

#[derive(Clone, Copy)]
pub struct VenueSpec {
    pub venue: &'static str,
    pub market: &'static str, // "spot" | "perp"
    pub max_streams_per_conn: usize,
    pub url: fn(&[String]) -> String,
    /// 连接后发送的订阅消息(币安 URL 内订阅=空;其余按各所批量上限分批)。
    pub subscribe: fn(&[String]) -> Vec<String>,
    /// 一帧文本 → 统一符号+可缺侧 L1。非行情帧(ack/pong/error)返回 None。
    pub parse: fn(&str, i64) -> Option<ParsedTick>,
    pub ping: PingMode,
    /// venue 原生符号 → 统一符号(大写无分隔符)。监视器与解析器必须同源,否则键错位=永远误判 stale。
    pub normalize: fn(&str) -> String,
    /// 兜底宇宙 base(btc) → venue 原生符号。仅 Redis universe 缺失时使用。
    pub to_native: fn(&str) -> String,
    pub stale_secs: i64,
    pub stale_fraction: f64,
    pub tls: TlsMode,
}

impl VenueSpec {
    pub fn key(&self) -> String {
        format!("{}_{}", self.venue, self.market)
    }
}

// ---------- 工具 ----------

fn dec(v: &Value) -> Option<Decimal> {
    match v {
        Value::String(s) => Decimal::from_str(s).ok(),
        Value::Number(n) => Decimal::from_str(&n.to_string()).ok(),
        _ => None,
    }
}

fn i64_of(v: &Value) -> Option<i64> {
    match v {
        Value::String(s) => s.parse::<i64>().ok(),
        Value::Number(n) => n.as_i64(),
        _ => None,
    }
}

/// [["px","sz",...], ...] 取一档
fn level1(v: &Value) -> Option<(Decimal, Decimal)> {
    let l = v.as_array()?.first()?.as_array()?;
    Some((dec(l.first()?)?, dec(l.get(1)?)?))
}

fn strip_seps_upper(s: &str) -> String {
    s.chars().filter(|c| *c != '-' && *c != '_').collect::<String>().to_uppercase()
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

// ---------- 币安(combined stream,URL 内订阅,协议 Ping/Pong) ----------

fn binance_parse(text: &str, recv_ts: i64) -> Option<ParsedTick> {
    let combined: BinanceCombinedStream = serde_json::from_str(text).ok()?;
    let d = combined.data;
    Some(ParsedTick {
        symbol: d.symbol.to_uppercase(),
        bid: Some((d.bid_price, d.bid_qty)),
        ask: Some((d.ask_price, d.ask_qty)),
        ts: d.timestamp.unwrap_or(recv_ts), // spot 无事件时间 T → 收帧本地时间(与 coin 同语义)
    })
}

fn binance_streams(symbols: &[String]) -> String {
    symbols.iter().map(|s| format!("{}@bookTicker", s.to_lowercase())).collect::<Vec<_>>().join("/")
}

pub const BINANCE_SPOT: VenueSpec = VenueSpec {
    venue: "binance",
    market: "spot",
    max_streams_per_conn: 200,
    url: |s| format!("wss://stream.binance.com:9443/stream?streams={}", binance_streams(s)),
    subscribe: |_| Vec::new(),
    parse: binance_parse,
    ping: PingMode::Protocol,
    normalize: |s| s.to_uppercase(),
    to_native: |b| format!("{b}usdt"),
    stale_secs: 600,
    stale_fraction: 0.4,
    tls: TlsMode::Rustls,
};

pub const BINANCE_PERP: VenueSpec = VenueSpec {
    venue: "binance",
    market: "perp",
    max_streams_per_conn: 200,
    url: |s| format!("wss://fstream.binance.com/stream?streams={}", binance_streams(s)),
    subscribe: |_| Vec::new(),
    parse: binance_parse,
    ping: PingMode::Protocol,
    normalize: |s| s.to_uppercase(),
    to_native: |b| format!("{b}usdt"),
    stale_secs: 600,
    stale_fraction: 0.4,
    tls: TlsMode::Rustls,
};

// ---------- OKX(v5 public,bbo-tbt;客户端 20s 文本 "ping"→"pong") ----------

fn okx_parse(text: &str, _recv_ts: i64) -> Option<ParsedTick> {
    if text == "pong" {
        return None;
    }
    let v: Value = serde_json::from_str(text).ok()?;
    let inst = v.get("arg")?.get("instId")?.as_str()?;
    let d = v.get("data")?.as_array()?.first()?;
    Some(ParsedTick {
        symbol: okx_normalize(inst),
        bid: d.get("bids").and_then(level1),
        ask: d.get("asks").and_then(level1),
        ts: d.get("ts").and_then(i64_of)?,
    })
}

fn okx_normalize(s: &str) -> String {
    strip_seps_upper(s.trim_end_matches("-SWAP"))
}

fn okx_subscribe(symbols: &[String]) -> Vec<String> {
    symbols
        .chunks(50)
        .map(|c| {
            let args: Vec<String> = c
                .iter()
                .map(|s| format!(r#"{{"channel":"bbo-tbt","instId":"{s}"}}"#))
                .collect();
            format!(r#"{{"op":"subscribe","args":[{}]}}"#, args.join(","))
        })
        .collect()
}

pub const OKX_SPOT: VenueSpec = VenueSpec {
    venue: "okx",
    market: "spot",
    max_streams_per_conn: 100,
    url: |_| "wss://ws.okx.com:8443/ws/v5/public".to_string(),
    subscribe: okx_subscribe,
    parse: okx_parse,
    ping: PingMode::Text { build: || "ping".to_string(), every_secs: 20 },
    normalize: okx_normalize,
    to_native: |b| format!("{}-USDT", b.to_uppercase()),
    stale_secs: 600,
    stale_fraction: 0.5,
    tls: TlsMode::Rustls,
};

pub const OKX_PERP: VenueSpec = VenueSpec {
    venue: "okx",
    market: "perp",
    max_streams_per_conn: 100,
    url: |_| "wss://ws.okx.com:8443/ws/v5/public".to_string(),
    subscribe: okx_subscribe,
    parse: okx_parse,
    ping: PingMode::Text { build: || "ping".to_string(), every_secs: 20 },
    normalize: okx_normalize,
    to_native: |b| format!("{}-USDT-SWAP", b.to_uppercase()),
    stale_secs: 600,
    stale_fraction: 0.5,
    tls: TlsMode::Rustls,
};

// ---------- Bybit(v5 public,orderbook.1;snapshot+delta 合并;{"op":"ping"}) ----------

fn bybit_parse(text: &str, _recv_ts: i64) -> Option<ParsedTick> {
    let v: Value = serde_json::from_str(text).ok()?;
    let topic = v.get("topic")?.as_str()?;
    if !topic.starts_with("orderbook.1.") {
        return None;
    }
    let d = v.get("data")?;
    let sym = d.get("s")?.as_str()?;
    // delta 帧变动侧才有值;size=0 的一档=删除(等下一帧新一档),按无变化处理
    let side = |k: &str| -> Option<(Decimal, Decimal)> {
        let (p, s) = level1(d.get(k)?)?;
        if s <= Decimal::ZERO { None } else { Some((p, s)) }
    };
    Some(ParsedTick {
        symbol: sym.to_uppercase(),
        bid: side("b"),
        ask: side("a"),
        ts: v.get("ts").and_then(i64_of)?,
    })
}

fn bybit_subscribe(symbols: &[String]) -> Vec<String> {
    symbols
        .chunks(10) // spot 每请求 ≤10 args
        .map(|c| {
            let args: Vec<String> =
                c.iter().map(|s| format!(r#""orderbook.1.{s}""#)).collect();
            format!(r#"{{"op":"subscribe","args":[{}]}}"#, args.join(","))
        })
        .collect()
}

pub const BYBIT_SPOT: VenueSpec = VenueSpec {
    venue: "bybit",
    market: "spot",
    max_streams_per_conn: 100,
    url: |_| "wss://stream.bybit.com/v5/public/spot".to_string(),
    subscribe: bybit_subscribe,
    parse: bybit_parse,
    ping: PingMode::Text { build: || r#"{"op":"ping"}"#.to_string(), every_secs: 20 },
    normalize: |s| s.to_uppercase(),
    to_native: |b| format!("{}USDT", b.to_uppercase()),
    stale_secs: 600,
    stale_fraction: 0.5,
    tls: TlsMode::Rustls,
};

pub const BYBIT_PERP: VenueSpec = VenueSpec {
    venue: "bybit",
    market: "perp",
    max_streams_per_conn: 100,
    url: |_| "wss://stream.bybit.com/v5/public/linear".to_string(),
    subscribe: bybit_subscribe,
    parse: bybit_parse,
    ping: PingMode::Text { build: || r#"{"op":"ping"}"#.to_string(), every_secs: 20 },
    normalize: |s| s.to_uppercase(),
    to_native: |b| format!("{}USDT", b.to_uppercase()),
    stale_secs: 600,
    stale_fraction: 0.5,
    tls: TlsMode::Rustls,
};

// ---------- Gate(v4,book_ticker 全量推;ping 帧带时间戳) ----------
// 注意:futures 的 B/A 是 **张数(合约数,整数)**,币量换算需乘 quanto multiplier
// (xv 已趟过的口径命门)——feed 按原样发布,换算在下游消费者做。

fn gate_parse(text: &str, _recv_ts: i64) -> Option<ParsedTick> {
    let v: Value = serde_json::from_str(text).ok()?;
    let ch = v.get("channel")?.as_str()?;
    if !ch.ends_with(".book_ticker") || v.get("event")?.as_str()? != "update" {
        return None;
    }
    let r = v.get("result")?;
    Some(ParsedTick {
        symbol: strip_seps_upper(r.get("s")?.as_str()?),
        bid: Some((dec(r.get("b")?)?, dec(r.get("B")?)?)),
        ask: Some((dec(r.get("a")?)?, dec(r.get("A")?)?)),
        ts: r.get("t").and_then(i64_of)?,
    })
}

fn gate_sub_msg(channel: &str, symbols: &[String]) -> Vec<String> {
    // 单消息整 chunk 订阅
    let payload: Vec<String> = symbols.iter().map(|s| format!(r#""{s}""#)).collect();
    vec![format!(
        r#"{{"time":{},"channel":"{channel}.book_ticker","event":"subscribe","payload":[{}]}}"#,
        now_secs(),
        payload.join(",")
    )]
}

fn gate_spot_subscribe(symbols: &[String]) -> Vec<String> {
    gate_sub_msg("spot", symbols)
}

fn gate_perp_subscribe(symbols: &[String]) -> Vec<String> {
    gate_sub_msg("futures", symbols)
}

pub const GATE_SPOT: VenueSpec = VenueSpec {
    venue: "gate",
    market: "spot",
    max_streams_per_conn: 100,
    url: |_| "wss://api.gateio.ws/ws/v4/".to_string(),
    subscribe: gate_spot_subscribe,
    parse: gate_parse,
    ping: PingMode::Text {
        build: || format!(r#"{{"time":{},"channel":"spot.ping"}}"#, now_secs()),
        every_secs: 15,
    },
    normalize: |s| strip_seps_upper(s),
    to_native: |b| format!("{}_USDT", b.to_uppercase()),
    stale_secs: 900,
    stale_fraction: 0.6,
    tls: TlsMode::NativeTls,
};

pub const GATE_PERP: VenueSpec = VenueSpec {
    venue: "gate",
    market: "perp",
    max_streams_per_conn: 100,
    url: |_| "wss://fx-ws.gateio.ws/v4/ws/usdt".to_string(),
    subscribe: gate_perp_subscribe,
    parse: gate_parse,
    ping: PingMode::Text {
        build: || format!(r#"{{"time":{},"channel":"futures.ping"}}"#, now_secs()),
        every_secs: 15,
    },
    normalize: |s| strip_seps_upper(s),
    to_native: |b| format!("{}_USDT", b.to_uppercase()),
    stale_secs: 900,
    stale_fraction: 0.6,
    tls: TlsMode::NativeTls,
};

// ---------- Bitget(v2 public,books1;裸文本 "ping"→"pong") ----------

fn bitget_parse(text: &str, _recv_ts: i64) -> Option<ParsedTick> {
    if text == "pong" {
        return None;
    }
    let v: Value = serde_json::from_str(text).ok()?;
    let arg = v.get("arg")?;
    if arg.get("channel")?.as_str()? != "books1" {
        return None;
    }
    let inst = arg.get("instId")?.as_str()?;
    let d = v.get("data")?.as_array()?.first()?;
    Some(ParsedTick {
        symbol: inst.to_uppercase(),
        bid: d.get("bids").and_then(level1),
        ask: d.get("asks").and_then(level1),
        ts: d.get("ts").and_then(i64_of)?,
    })
}

fn bitget_sub_msgs(inst_type: &str, symbols: &[String]) -> Vec<String> {
    symbols
        .chunks(50)
        .map(|c| {
            let args: Vec<String> = c
                .iter()
                .map(|s| {
                    format!(r#"{{"instType":"{inst_type}","channel":"books1","instId":"{s}"}}"#)
                })
                .collect();
            format!(r#"{{"op":"subscribe","args":[{}]}}"#, args.join(","))
        })
        .collect()
}

fn bitget_spot_subscribe(symbols: &[String]) -> Vec<String> {
    bitget_sub_msgs("SPOT", symbols)
}

fn bitget_perp_subscribe(symbols: &[String]) -> Vec<String> {
    bitget_sub_msgs("USDT-FUTURES", symbols)
}

pub const BITGET_SPOT: VenueSpec = VenueSpec {
    venue: "bitget",
    market: "spot",
    max_streams_per_conn: 100,
    url: |_| "wss://ws.bitget.com/v2/ws/public".to_string(),
    subscribe: bitget_spot_subscribe,
    parse: bitget_parse,
    ping: PingMode::Text { build: || "ping".to_string(), every_secs: 25 },
    normalize: |s| s.to_uppercase(),
    to_native: |b| format!("{}USDT", b.to_uppercase()),
    stale_secs: 900,
    stale_fraction: 0.6,
    tls: TlsMode::Rustls,
};

pub const BITGET_PERP: VenueSpec = VenueSpec {
    venue: "bitget",
    market: "perp",
    max_streams_per_conn: 100,
    url: |_| "wss://ws.bitget.com/v2/ws/public".to_string(),
    subscribe: bitget_perp_subscribe,
    parse: bitget_parse,
    ping: PingMode::Text { build: || "ping".to_string(), every_secs: 25 },
    normalize: |s| s.to_uppercase(),
    to_native: |b| format!("{}USDT", b.to_uppercase()),
    stale_secs: 900,
    stale_fraction: 0.6,
    tls: TlsMode::Rustls,
};

/// 已注册的全部 spec;按 DCM_FEED_VENUES(逗号分隔 spec.key)筛选启用。
pub const ALL_SPECS: &[VenueSpec] = &[
    BINANCE_SPOT, BINANCE_PERP,
    OKX_SPOT, OKX_PERP,
    BYBIT_SPOT, BYBIT_PERP,
    GATE_SPOT, GATE_PERP,
    BITGET_SPOT, BITGET_PERP,
];
