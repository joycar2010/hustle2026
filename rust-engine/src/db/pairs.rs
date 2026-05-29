use deadpool_postgres::Pool;
use tracing::info;

#[derive(Clone, Debug)]
pub struct PairConfig {
    pub pair_code: String,
    pub a_symbol: String,
    pub mt5_symbol: String,
    pub conversion_factor: f64,
    pub mt5_platform_id: i32,
    pub a_platform_id: i32,
    pub bridge_url: String,
}

pub async fn load_pairs(pool: &Pool) -> Vec<PairConfig> {
    let client = pool.get().await.expect("DB pool exhausted");
    let bridges = load_system_bridges(&client).await;

    let rows = client
        .query(
            "SELECT hp.pair_code, sa.symbol, sb.symbol, hp.conversion_factor,
                    sb.platform_id, sa.platform_id
             FROM hedging_pairs hp
             JOIN platform_symbols sa ON hp.symbol_a_id = sa.id
             JOIN platform_symbols sb ON hp.symbol_b_id = sb.id
             WHERE hp.is_active = true
             ORDER BY hp.sort_order",
            &[],
        )
        .await
        .expect("Failed to load pairs");

    let mut pairs = Vec::new();
    for row in &rows {
        let pair_code: String = row.get(0);
        let a_symbol: String = row.get(1);
        let mt5_symbol: String = row.get(2);
        let conversion_factor: f64 = row.get(3);
        let mt5_platform_id: i16 = row.get(4);
        let a_platform_id: i16 = row.get(5);
        let bridge_url = bridges
            .iter()
            .find(|(pid, _)| *pid == mt5_platform_id as i32)
            .map(|(_, url)| url.clone())
            .unwrap_or_default();

        pairs.push(PairConfig {
            pair_code,
            a_symbol,
            mt5_symbol,
            conversion_factor,
            mt5_platform_id: mt5_platform_id as i32,
            a_platform_id: a_platform_id as i32,
            bridge_url,
        });
    }
    info!("Loaded {} active pairs", pairs.len());
    for p in &pairs {
        info!("  {} => A:{} (plat={}) B:{} bridge={}", p.pair_code, p.a_symbol, p.a_platform_id, p.mt5_symbol, p.bridge_url);
    }
    pairs
}

async fn load_system_bridges(client: &deadpool_postgres::Client) -> Vec<(i32, String)> {
    let rows = client
        .query(
            "SELECT a.platform_id,
                    COALESCE(mc.bridge_url, CONCAT('http://172.31.14.113:', mc.bridge_service_port))
             FROM mt5_clients mc JOIN accounts a ON mc.account_id = a.account_id
             WHERE mc.is_active = true AND mc.is_system_service = true",
            &[],
        )
        .await
        .unwrap_or_default();

    rows.iter()
        .map(|r| {
            let pid: i16 = r.get(0);
            let url: String = r.get(1);
            (pid as i32, url)
        })
        .collect()
}

pub fn symbols_by_platform(pairs: &[PairConfig], platform_id: i32) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    pairs
        .iter()
        .filter(|p| p.a_platform_id == platform_id)
        .filter_map(|p| {
            if seen.insert(p.a_symbol.clone()) {
                Some(p.a_symbol.clone())
            } else {
                None
            }
        })
        .collect()
}

pub fn build_binance_streams_url(symbols: &[String]) -> String {
    let streams: Vec<String> = symbols
        .iter()
        .map(|s| format!("{}@bookTicker", s.to_lowercase()))
        .collect();
    format!(
        "wss://fstream.binance.com/stream?streams={}",
        streams.join("/")
    )
}
