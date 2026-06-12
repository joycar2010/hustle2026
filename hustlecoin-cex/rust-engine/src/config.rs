use rust_decimal::Decimal;
use std::env;
use std::str::FromStr;

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub redis_url: String,
    pub symbols: Vec<String>,
    /// 任一腿(现货/合约)超过此毫秒数未更新 → 视为 stale,不发布点差。
    /// 防止 live腿×stale腿 算出假大点差(WS 单 symbol 流静默死亡 / 整币停更)。
    pub max_staleness_ms: i64,
    /// 点差幅度绝对值超过此值(%)→ 视为坏数据不发布(兜底:T 仍刷新的冻结盘口 /
    /// 已下架/熔断合约 emit 0 价等,ts 护栏抓不到的情形)。给宽容默认,只挡明显异常。
    pub max_spread_pct: Decimal,
}

impl AppConfig {
    pub fn load() -> Self {
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

        let symbols = get_top_futures_symbols();

        Self {
            redis_url,
            symbols,
            max_staleness_ms,
            max_spread_pct,
        }
    }
}

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
        "xmrusdt", "belusdt", "alphausdt", "atausdt", "audiousdt", "c98usdt", "darusdt",
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
