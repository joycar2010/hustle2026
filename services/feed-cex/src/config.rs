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
            .unwrap_or_else(|_| {
                "binance_spot,binance_perp,okx_spot,okx_perp,bybit_spot,bybit_perp,\
                 gate_spot,gate_perp,bitget_spot,bitget_perp"
                    .to_string()
            })
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        Self { redis_url, enabled }
    }
}

/// 从 Redis 读某 venue 的交易宇宙(JSON 字符串数组,**venue 原生符号**原样返回——
/// OKX/Gate 等符号带大小写与分隔符,订阅必须用原生格式,统一化只发生在发布键)。
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
    Some(arr.into_iter().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
}

/// 兜底宇宙 base 列表:仅当 Redis universe 缺失时使用(经 spec.to_native 映射为各所原生符号),
/// 保证 feed 永不空订阅。生产宇宙由 Python 侧写 dcm:feed:universe:{venue}[:{market}] 全量管理。
pub fn fallback_bases() -> Vec<String> {
    [
        "btc", "eth", "bnb", "sol", "xrp", "doge", "ada", "avax", "dot", "link", "ltc",
        "bch", "atom", "etc", "fil", "apt", "arb", "op", "near", "sui", "sei", "tia",
        "wld", "pepe",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}
