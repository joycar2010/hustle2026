from fastapi import APIRouter
from ..core.redis import get_redis
from ..schemas import MarketDataResponse, SpreadResponse

router = APIRouter()

@router.get("/binance", response_model=MarketDataResponse)
def get_binance_market_data():
    redis_client = get_redis()
    data = redis_client.hgetall("market:binance:XAUUSDT")
    if not data:
        return {
            "bid": "0",
            "ask": "0",
            "last_price": "0",
            "timestamp": "0",
            "server_time": "0",
            "update_time": ""
        }
    return data

@router.get("/bybit-mt5", response_model=MarketDataResponse)
def get_bybit_mt5_market_data():
    redis_client = get_redis()
    data = redis_client.hgetall("market:bybit_mt5:XAUUSD.s")
    if not data:
        return {
            "bid": "0",
            "ask": "0",
            "last_price": "0",
            "timestamp": "0",
            "update_time": ""
        }
    return data

@router.get("/spread", response_model=SpreadResponse)
def get_spread_data():
    redis_client = get_redis()
    data = redis_client.hgetall("market:spread:XAU")
    if not data:
        return {
            "forward_spread": "0",
            "reverse_spread": "0",
            "binance_price": "0",
            "bybit_mt5_price": "0",
            "mt5_account_id": "",
            "update_time": ""
        }
    return data
