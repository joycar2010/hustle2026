use serde::Deserialize;
use tracing::warn;

#[derive(Deserialize)]
struct Mt5Tick {
    bid: Option<f64>,
    ask: Option<f64>,
}

pub struct Mt5Bridge {
    client: reqwest::Client,
    api_key: String,
}

impl Mt5Bridge {
    pub fn new(api_key: String) -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(3))
                .build()
                .unwrap(),
            api_key,
        }
    }

    pub async fn get_tick(&self, bridge_url: &str, symbol: &str) -> Option<(f64, f64)> {
        let url = format!("{}/mt5/tick/{}", bridge_url, symbol);
        let resp = self
            .client
            .get(&url)
            .header("X-Api-Key", &self.api_key)
            .send()
            .await
            .ok()?;
        let t: Mt5Tick = resp.json().await.ok()?;
        match (t.bid, t.ask) {
            (Some(b), Some(a)) if b > 0.0 && a > 0.0 => Some((b, a)),
            _ => {
                warn!("[MT5Bridge] no tick for {} from {}", symbol, bridge_url);
                None
            }
        }
    }

    pub async fn get_symbol_info(
        &self,
        bridge_url: &str,
        symbol: &str,
    ) -> Option<serde_json::Value> {
        let url = format!("{}/mt5/symbol_info/{}", bridge_url, symbol);
        let resp = self
            .client
            .get(&url)
            .header("X-Api-Key", &self.api_key)
            .send()
            .await
            .ok()?;
        resp.json().await.ok()
    }
}
