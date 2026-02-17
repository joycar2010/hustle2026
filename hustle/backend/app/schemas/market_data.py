from pydantic import BaseModel
from typing import Optional

class MarketDataResponse(BaseModel):
    bid: str
    ask: str
    last_price: str
    timestamp: str
    server_time: Optional[str] = None
    update_time: str

class SpreadResponse(BaseModel):
    forward_spread: str
    reverse_spread: str
    binance_price: str
    bybit_mt5_price: str
    mt5_account_id: Optional[str] = None
    update_time: str
