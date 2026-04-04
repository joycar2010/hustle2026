from pydantic_settings import BaseSettings
from typing import List
import json


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Database (从.env文件读取，以下为默认值)
    DATABASE_URL: str = "postgresql://postgres:Lk106504@127.0.0.1:5432/postgres"
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "postgres"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "Lk106504"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT
    SECRET_KEY: str  # Required from environment variable
    ENCRYPTION_KEY: str  # Required for API key encryption
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.SECRET_KEY or self.SECRET_KEY == "your-secret-key-here-change-in-production":
            raise ValueError(
                "SECRET_KEY must be set in environment variables. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        if not self.ENCRYPTION_KEY:
            raise ValueError(
                "ENCRYPTION_KEY must be set in environment variables for API key encryption. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )

    # Binance API
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_TESTNET: bool = False
    BINANCE_API_BASE: str = "https://fapi.binance.com"
    BINANCE_WS_BASE: str = "wss://fstream.binance.com"

    # Bybit API
    BYBIT_API_KEY: str = ""
    BYBIT_API_SECRET: str = ""
    BYBIT_TESTNET: bool = False
    BYBIT_API_BASE: str = "https://api.bybit.com"
    BYBIT_WS_BASE: str = "wss://stream.bybit.com"

    # Proxy settings (optional, for accessing blocked APIs)
    HTTP_PROXY: str = ""
    HTTPS_PROXY: str = ""

    # Qingguo Proxy Service (青果网络代理服务)
    QINGGUO_API_KEY: str = ""  # 青果网络API密钥

    # Bybit MT5
    BYBIT_MT5_ID: str = ""
    BYBIT_MT5_SERVER: str = ""
    BYBIT_MT5_PASSWORD: str = ""

    # MT5 Trading Configuration
    MT5_DEFAULT_SYMBOL: str = "XAUUSD+"  # Default trading symbol for MT5
    MT5_DEFAULT_SYMBOLS: List[str] = ["XAUUSD+"]  # List of default symbols to monitor

    # MT5 Windows Agent
    MT5_AGENT_URL: str = "http://172.31.14.113:8765"
    MT5_AGENT_API_KEY: str = ""
    MT5_BRIDGE_API_KEY: str = ""

    # System
    APP_NAME: str = "Hustle2026"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = '["http://localhost:3000","http://localhost:3001","http://localhost:3002"]'
    ENVIRONMENT: str = "development"

    # Market Data Configuration
    MARKET_DATA_UPDATE_INTERVAL: int = 1  # seconds (real-time market data refresh)
    SPREAD_RECORD_INTERVAL: int = 1  # seconds
    ACCOUNT_SYNC_INTERVAL: int = 5  # seconds
    SPREAD_ALERT_COOLDOWN: int = 300  # seconds (cooldown time for spread alerts - 5 minutes)

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 100

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from JSON string"""
        try:
            return json.loads(self.CORS_ORIGINS)
        except:
            return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()
