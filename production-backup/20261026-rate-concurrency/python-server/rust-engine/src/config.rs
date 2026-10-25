use rust_decimal::Decimal;
use std::collections::BTreeSet;
use std::env;
use std::str::FromStr;

/// The execution universe is the only source for new-action eligibility.
pub const EXECUTION_UNIVERSE_KEY: &str = "engine:universe";
/// Non-terminal Position symbols are retained for exit-only market data.  This
/// key is never consumed by Python borrow/open gates.
pub const EXIT_UNIVERSE_KEY: &str = "engine:exit-universe";

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub redis_url: String,
    /// 订阅的行情宇宙(小写 symbol,如 stgusdt)。运行时从 Redis
    /// engine:universe 与 engine:exit-universe 的并集加载。
    /// engine:exit-universe 只保留已有非终态 Position 的退出行情。
    /// 缺失时保持空集合并 fail-closed；硬编码期货列表可能包含下架币，
    /// 因此不能作为交易订阅回退。
    pub symbols: Vec<String>,
    /// 任一腿(现货/合约)超过此毫秒数未更新 → 视为 stale,不发布点差。
    /// 防止 live腿×stale腿 算出假大点差(WS 单 symbol 流静默死亡 / 整币停更)。
    pub max_staleness_ms: i64,
    /// 点差幅度绝对值超过此值(%)→ 视为坏数据不发布(兜底:T 仍刷新的冻结盘口 /
    /// 已下架/熔断合约 emit 0 价等,ts 护栏抓不到的情形)。给宽容默认,只挡明显异常。
    pub max_spread_pct: Decimal,
    /// 冻结护栏:某腿买一/卖一价连续此毫秒数未变 → 视为价格冻结,不发布。
    /// 补新鲜度护栏的缝:bookTicker 在「数量」变化时也推送(价不变也刷新 ts),
    /// 冻结价×活腿=假基差却被 ts 护栏放行。活跃币价毫秒级跳动,永不触发(默认 60s)。
    pub frozen_ms: i64,
}

impl AppConfig {
    pub async fn load() -> Self {
        let redis_url =
            env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string());

        // Keep the newer Python name canonical while accepting the original
        // Rust service variable for existing deployments.  Both sides then
        // enforce the same local-WS freshness fence.
        let max_staleness_ms = ["BINANCE_WS_MAX_AGE_MS", "MAX_STALENESS_MS"]
            .into_iter()
            .filter_map(|name| env::var(name).ok())
            .filter_map(|value| value.parse::<i64>().ok())
            .find(|value| *value > 0)
            .unwrap_or(10_000);

        let max_spread_pct = env::var("MAX_SPREAD_PCT")
            .ok()
            .and_then(|v| Decimal::from_str(&v).ok())
            .filter(|v| *v > Decimal::ZERO)
            .unwrap_or_else(|| Decimal::from(8));

        let frozen_ms = env::var("FROZEN_MS")
            .ok()
            .and_then(|v| v.parse::<i64>().ok())
            .filter(|v| *v > 0)
            .unwrap_or(60_000);

        let symbols = load_universe(&redis_url).await;

        Self {
            redis_url,
            symbols,
            max_staleness_ms,
            max_spread_pct,
            frozen_ms,
        }
    }
}

/// 从 Redis 读取交易/退出行情宇宙的并集。
/// 缺失或解析失败时返回空集合；执行引擎必须等待业务侧准入集合，不能猜测币种。
async fn load_universe(redis_url: &str) -> Vec<String> {
    match try_load_universe(redis_url).await {
        Some(v) if !v.is_empty() => {
            tracing::info!(count = v.len(), "Loaded execution plus exit-only WS universe");
            v
        }
        _ => {
            tracing::warn!("execution/exit universe missing or empty — engine is fail-closed until eligibility feed is available");
            Vec::new()
        }
    }
}

/// 公开版:ws 模块每次重连时调用,只返回原始列表(不 fallback),供增量对比。
/// 空列表=Redis 暂时不可读,调用方保留现有 symbols 不变。
pub async fn load_universe_symbols(redis_url: &str) -> Vec<String> {
    try_load_universe(redis_url).await.unwrap_or_default()
}

/// Checked variant used by the WS refresh watcher. ``None`` means Redis or a
/// JSON payload was unavailable; an empty ``Some`` is an authoritative empty
/// universe and must cause the current subscription to drain.
pub async fn load_universe_symbols_checked(redis_url: &str) -> Option<Vec<String>> {
    try_load_universe(redis_url).await
}

async fn try_load_universe(redis_url: &str) -> Option<Vec<String>> {
    let client = redis::Client::open(redis_url).ok()?;
    let mut conn = client.get_multiplexed_async_connection().await.ok()?;
    let values: Vec<Option<String>> = redis::cmd("MGET")
        .arg(EXECUTION_UNIVERSE_KEY)
        .arg(EXIT_UNIVERSE_KEY)
        .query_async(&mut conn)
        .await
        .ok()?;
    let mut values = values.into_iter();
    let execution_raw = values.next()?;
    let exit_raw = values.next()?;
    merge_universe_payloads(execution_raw, exit_raw)
}

fn merge_universe_payloads(
    execution_raw: Option<String>,
    exit_raw: Option<String>,
) -> Option<Vec<String>> {
    // An explicit JSON [] is authoritative, but a missing execution key
    // usually means Redis was flushed or the publisher has not completed its
    // first cycle. Keep the previous subscription in that case.
    if execution_raw.is_none() {
        return None;
    }
    let execution = parse_symbol_key(execution_raw)?;
    let exit_only = parse_symbol_key(exit_raw)?;
    let mut symbols = BTreeSet::new();
    symbols.extend(execution);
    symbols.extend(exit_only);
    Some(symbols.into_iter().collect())
}

fn parse_symbol_key(raw: Option<String>) -> Option<Vec<String>> {
    let Some(raw) = raw else {
        return Some(Vec::new());
    };
    let arr: Vec<String> = serde_json::from_str(&raw).ok()?;
    Some(
        arr.into_iter()
            .filter_map(|symbol| {
                let normalized = symbol.trim().to_ascii_lowercase();
                (is_valid_usdt_symbol(&normalized)).then_some(normalized)
            })
            .collect(),
    )
}

/// Redis is a control-plane boundary.  Keep malformed values out of the
/// combined-stream URL and out of the ticker map even if a stale publisher or
/// legacy database row writes an unexpected symbol.
fn is_valid_usdt_symbol(symbol: &str) -> bool {
    let Some(base) = symbol.strip_suffix("usdt") else {
        return false;
    };
    !base.is_empty()
        && base.len() <= 26
        && base.bytes().all(|byte| byte.is_ascii_alphanumeric())
}

#[cfg(test)]
mod tests {
    use super::{merge_universe_payloads, parse_symbol_key};

    #[test]
    fn missing_exit_key_is_empty_but_payload_symbols_are_normalized() {
        assert_eq!(parse_symbol_key(None), Some(Vec::new()));
        assert_eq!(
            parse_symbol_key(Some(r#"["BTCUSDT", " ethusdt ", ""]"#.to_string())),
            Some(vec!["btcusdt".to_string(), "ethusdt".to_string()]),
        );
    }

    #[test]
    fn malformed_universe_payload_fails_closed() {
        assert_eq!(parse_symbol_key(Some("not-json".to_string())), None);
    }

    #[test]
    fn malformed_symbols_are_filtered_before_ws_url_construction() {
        assert_eq!(
            parse_symbol_key(Some(
                r#"["BTCUSDT", " bad/slashUSDT ", "ETHUSD", "1000SATSUSDT"]"#
                    .to_string(),
            )),
            Some(vec!["btcusdt".to_string(), "1000satsusdt".to_string()]),
        );
    }

    #[test]
    fn missing_execution_key_is_unavailable_but_explicit_empty_is_authoritative() {
        assert_eq!(
            merge_universe_payloads(None, Some("[\"btcusdt\"]".to_string())),
            None
        );
        assert_eq!(
            merge_universe_payloads(Some("[]".to_string()), None),
            Some(Vec::new())
        );
    }
}

// Kept as a private fixture for operators/tests that need a sample symbol list;
// it is never used as an execution fallback.
#[allow(dead_code)]
fn get_top_futures_symbols() -> Vec<String> {
    vec![
        "btcusdt", "ethusdt", "bnbusdt", "solusdt", "xrpusdt", "dogeusdt", "adausdt",
        "avaxusdt", "dotusdt", "linkusdt", "maticusdt", "uniusdt", "ltcusdt", "bchusdt",
        "atomusdt", "etcusdt", "filusdt", "aptusdt", "arbusdt", "opusdt", "nearusdt",
        "ftmusdt", "sandusdt", "manausdt", "axsusdt", "galausdt", "apeusdt", "gmtusdt",
        "ldousdt", "injusdt", "suiusdt", "seiusdt", "tiausdt", "jupusdt", "wldusdt",
        "strkusdt", "pythusdt", "ondousdt", "enausdt", "wusdt", "arusdt", "rndrusdt",
        "fetusdt", "flokiusdt", "pepeusdt", "shibusdt", "bonkusdt", "wifusdt", "1000satsusdt",
        "ordiusdt", "runeusdt", "pendleusdt", "jupusdt", "ensusdt", "mkrusdt", "aaveusdt",
        "compusdt", "crvusdt", "snxusdt", "dydxusdt", "gmxusdt", "maskusdt", "enjusdt",
        "chzusdt", "imxusdt", "flowusdt", "minausdt", "ksmusdt", "zecusdt", "dashusdt",
        "neousdt", "wavesusdt", "zilusdt", "iostusdt", "ontusdt", "vetusdt", "thetausdt",
        "algousdt", "eosusdt", "xtzusdt", "icpusdt", "hbarusdt", "egldusdt", "qntusdt",
        "grtusdt", "ssvusdt", "cfxusdt", "ckbusdt", "stxusdt", "agixusdt", "rlcusdt",
        "celousdt", "sklusdt", "iotausdt", "kavausdt", "1inchusdt", "ankrusdt", "bakeusdt",
        "blzusdt", "cotiusdt", "dentusdt", "hotusdt", "ilvusdt", "joeusdt", "klayusdt",
        "lrcusdt", "oceanusdt", "renusdt", "sfpusdt", "tlmusdt", "tusdt", "xemusdt",
        "yfiusdt", "zenusdt", "balusdt", "bandusdt", "batusdt", "celrusdt", "ctkusdt",
        "duskusdt", "flmusdt", "hntusdt", "linausdt", "litusdt", "nknusdt", "ognusdt",
        "omgusdt", "reefusdt", "rvnusdt", "sxpusdt", "tomousdt", "trxusdt", "unfiusdt",
        "xmrusdt", "belusdt", "alphausdt", "audiousdt", "c98usdt", "darusdt",
        "degousdt", "arusdt", "highusdt", "hookusdt", "idusdt", "leverusdt", "lptusdt",
        "magicusdt", "mavusdt", "mtlusdt", "phbusdt", "radusdt", "rlcusdt", "ssvusdt",
        "woousdt", "yggusdt", "zrxusdt", "achusdt", "blurusdt", "eduusdt", "gasusdt",
        "glmusdt", "gnousdt", "lqtyusdt", "ntrnusdt", "oxtusdt", "perpusdt", "powrusdt",
        "rplusdt", "tokenusdt", "truusdt", "umausdt", "ustcusdt", "cakeusdt", "aiusdt",
        "altusdt", "roninusdt", "signusdt", "spkusdt", "2zusdt", "cgptusdt",
        "homeusdt", "fluxusdt", "kernelusdt", "gunusdt", "initusdt", "formusdt",
        "openusdt", "compusdt", "provenusdt", "axlusdt",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}
