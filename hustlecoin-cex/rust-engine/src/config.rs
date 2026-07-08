use rust_decimal::Decimal;
use std::env;
use std::str::FromStr;

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub redis_url: String,
    /// 订阅的交易宇宙(小写 symbol,如 stgusdt)。运行时从 Redis engine:universe 加载
    /// (由 python 业务侧按 symbols 表 active 全量写入,覆盖所有可套利币);缺失则 fallback。
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

        let max_staleness_ms = env::var("MAX_STALENESS_MS")
            .ok()
            .and_then(|v| v.parse::<i64>().ok())
            .filter(|v| *v > 0)
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

/// 从 Redis engine:universe 读交易宇宙(JSON 字符串数组,大小写不限 → 统一小写);
/// 缺失/解析失败/空集 → fallback 硬编码 top 列表(保证引擎永不空订阅)。
async fn load_universe(redis_url: &str) -> Vec<String> {
    match try_load_universe(redis_url).await {
        Some(v) if !v.is_empty() => {
            tracing::info!(count = v.len(), "Loaded trading universe from Redis engine:universe");
            v
        }
        _ => {
            let fb = get_top_futures_symbols();
            tracing::warn!(count = fb.len(), "engine:universe missing/empty — using hardcoded fallback");
            fb
        }
    }
}

/// 公开版:ws 模块每次重连时调用,只返回原始列表(不 fallback),供增量对比。
/// 空列表=Redis 暂时不可读,调用方保留现有 symbols 不变。
pub async fn load_universe_symbols(redis_url: &str) -> Vec<String> {
    try_load_universe(redis_url).await.unwrap_or_default()
}

async fn try_load_universe(redis_url: &str) -> Option<Vec<String>> {
    let client = redis::Client::open(redis_url).ok()?;
    let mut conn = client.get_multiplexed_async_connection().await.ok()?;
    let raw: Option<String> = redis::cmd("GET")
        .arg("engine:universe")
        .query_async(&mut conn)
        .await
        .ok()?;
    let raw = raw?;
    let arr: Vec<String> = serde_json::from_str(&raw).ok()?;
    Some(arr.into_iter().map(|s| s.to_lowercase()).collect())
}

// 兜底 top 列表:仅当 Redis engine:universe 缺失时使用,保证引擎永不空订阅
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
