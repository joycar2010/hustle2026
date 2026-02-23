from pydantic_settings import BaseSettings
from typing import List
import json


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "postgres"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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

    # Bybit MT5
    BYBIT_MT5_ID: str = ""
    BYBIT_MT5_SERVER: str = ""
    BYBIT_MT5_PASSWORD: str = ""

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
