from pydantic import BaseModel
from typing import Dict


class MarketQuote(BaseModel):
    """Schema for market quote data

    20260716 M1续(V1.1 §10 QuoteEnvelope精简版): 增加行情源时间戳 —
    src_ms=交易所/终端源时间(币安bookTicker E / MT5 tick time_msc),
    recv_ms=后端接收时间。timestamp语义不变(向后兼容)。
    新鲜度判断不再允许用本地now冒充源时间。"""

    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    timestamp: int
    src_ms: int | None = None
    recv_ms: int | None = None


class SpreadData(BaseModel):
    """Schema for spread calculation"""

    binance_quote: MarketQuote
    bybit_quote: MarketQuote
    forward_entry_spread: float  # bybit_ask - binance_bid
    forward_exit_spread: float  # binance_ask - bybit_bid
    reverse_entry_spread: float  # binance_ask - bybit_bid
    reverse_exit_spread: float  # bybit_ask - binance_bid
    timestamp: int
