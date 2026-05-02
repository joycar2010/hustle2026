use std::env;

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub redis_url: String,
    pub symbols: Vec<String>,
}

impl AppConfig {
    pub fn load() -> Self {
        let redis_url =
            env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string());

        let symbols = get_top_futures_symbols();

        Self { redis_url, symbols }
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
