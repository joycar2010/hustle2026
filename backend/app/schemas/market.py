from pydantic import BaseModel
from typing import Dict


class MarketQuote(BaseModel):
    """Schema for market quote data"""

    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    timestamp: int


class SpreadData(BaseModel):
    """Schema for spread calculation"""

    binance_quote: MarketQuote
    bybit_quote: MarketQuote
    forward_entry_spread: float  # bybit_ask - binance_bid
    forward_exit_spread: float  # binance_ask - bybit_bid
    reverse_entry_spread: float  # binance_ask - bybit_bid
    reverse_exit_spread: float  # bybit_ask - binance_bid
    timestamp: int
