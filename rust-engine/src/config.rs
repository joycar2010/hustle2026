use std::env;

#[derive(Clone, Debug)]
pub struct AppConfig {
    pub database_url: String,
    pub redis_url: String,
    pub secret_key: String,
    pub mt5_api_key: String,
    pub listen_addr: String,
}

impl AppConfig {
    pub fn from_env() -> Self {
        Self {
            database_url: env::var("DATABASE_URL")
                .unwrap_or_else(|_| "postgres://postgres:Lk106504@127.0.0.1:5432/postgres".into()),
            redis_url: env::var("REDIS_URL")
                .unwrap_or_else(|_| "redis://127.0.0.1:6379/0".into()),
            secret_key: env::var("SECRET_KEY")
                .unwrap_or_else(|_| "hustle2026-secret-key-prod".into()),
            mt5_api_key: env::var("MT5_API_KEY")
                .unwrap_or_else(|_| "OQ6bUimHZDmXEZzJKE".into()),
            listen_addr: env::var("LISTEN_ADDR")
                .unwrap_or_else(|_| "0.0.0.0:8090".into()),
        }
    }
}
