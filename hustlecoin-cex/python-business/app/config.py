from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:cex_trading_2026@127.0.0.1:5432/cex_trading"
    redis_url: str = "redis://10.0.1.95:6379"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    binance_api_timeout: int = 10
    symbol_sync_on_startup: bool = True
    symbol_sync_interval_hours: int = 24
    jwt_secret: str = "changeme"
    jwt_expire_hours: int = 24
    encryption_key: str = ""
    allowed_origins: str = ""
    aicoin_api_key: str = ""
    aicoin_api_secret: str = ""

    class Config:
        env_prefix = "CEX_"


settings = Settings()
