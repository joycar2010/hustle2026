from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """应用程序配置"""
    # 数据库配置
    DATABASE_URL: str = "postgresql://admin:password@localhost:5432/hustle_db"
    
    # 认证配置
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # 应用配置
    APP_NAME: str = "Hustle XAU套利系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # Redis配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # API配置
    API_V1_STR: str = "/api/v1"
    
    # 加密配置
    ENCRYPTION_KEY: str = ""
    
    # 外部API配置
    BINANCE_API_BASE: str = "https://fapi.binance.com"
    BINANCE_WS_URL: str = "wss://fstream.binance.com/ws"
    BYBIT_API_BASE: str = "https://api.bybit.com"
    BYBIT_MT5_WS_URL: str = "wss://stream.bybit.com/v5/public/linear"
    
    # MT5账户配置
    MT5_ACCOUNT_ID: str = ""
    MT5_PASSWORD: str = ""
    MT5_SERVER: str = ""
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# 创建全局配置实例
settings = Settings()
