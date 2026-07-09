use std::env;

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub redis_url: String,
    /// 启用的 (venue,market) 流,逗号分隔。默认币安双市场。
    pub enabled: Vec<String>,
}

impl AppConfig {
    pub fn load() -> Self {
        let redis_url = env::var("DCM_REDIS_URL")
            .or_else(|_| env::var("REDIS_URL"))
            .unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string());
        let enabled = env::var("DCM_FEED_VENUES")
            .unwrap_or_else(|_| "binance_spot,binance_usdm".to_string())
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        Self { redis_url, enabled }
    }
}

/// 从 Redis 读某 venue 的交易宇宙(JSON 字符串数组→统一小写)。
/// 先查 dcm:feed:universe:{venue}:{market},再 dcm:feed:universe:{venue}。
/// 空 = Redis 暂不可读/未配置,调用方自行 fallback / 保留现列表(与 coin 同语义)。
pub async fn load_universe(redis_url: &str, venue: &str, market: &str) -> Vec<String> {
    for key in [
        format!("dcm:feed:universe:{venue}:{market}"),
        format!("dcm:feed:universe:{venue}"),
    ] {
        if let Some(v) = try_get_universe(redis_url, &key).await {
            if !v.is_empty() {
                return v;
            }
        }
    }
    Vec::new()
}

async fn try_get_universe(redis_url: &str, key: &str) -> Option<Vec<String>> {
    let client = redis::Client::open(redis_url).ok()?;
    let mut conn = client.get_multiplexed_async_connection().await.ok()?;
    let raw: Option<String> = redis::cmd("GET").arg(key).query_async(&mut conn).await.ok()?;
    let arr: Vec<String> = serde_json::from_str(&raw?).ok()?;
    Some(arr.into_iter().map(|s| s.to_lowercase()).collect())
}

/// 兜底宇宙:仅当 Redis universe 缺失时使用,保证 feed 永不空订阅。
/// 生产宇宙由 Python 侧(采样器/decision)写 dcm:feed:universe:{venue} 全量管理。
pub fn fallback_universe() -> Vec<String> {
    [
        "btcusdt", "ethusdt", "bnbusdt", "solusdt", "xrpusdt", "dogeusdt", "adausdt",
        "avaxusdt", "dotusdt", "linkusdt", "ltcusdt", "bchusdt", "atomusdt", "etcusdt",
        "filusdt", "aptusdt", "arbusdt", "opusdt", "nearusdt", "suiusdt", "seiusdt",
        "tiausdt", "wldusdt", "pepeusdt",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}
