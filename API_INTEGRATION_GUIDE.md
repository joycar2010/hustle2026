# API Integration Quick Reference

## Binance Futures API

### Base URLs
- REST: `https://fapi.binance.com`
- WebSocket: `wss://fstream.binance.com`
- Testnet REST: `https://testnet.binancefuture.com`
- Testnet WS: `wss://stream.binancefuture.com`

### Authentication
```python
import hmac
import hashlib
import time

def sign_request(params, secret_key):
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

# Example request
params = {
    'symbol': 'XAUUSDT',
    'timestamp': int(time.time() * 1000)
}
params['signature'] = sign_request(params, API_SECRET)
```

### Key Endpoints for Hustle System

#### 1. Server Time (Time Sync)
```
GET /fapi/v1/time
```
Response:
```json
{
  "serverTime": 1499827319559
}
```

#### 2. Market Data - Latest Price
```
GET /fapi/v1/ticker/price?symbol=XAUUSDT
```
Response:
```json
{
  "symbol": "XAUUSDT",
  "price": "2650.50"
}
```

#### 3. Market Data - Best Bid/Ask (Book Ticker)
```
GET /fapi/v1/ticker/bookTicker?symbol=XAUUSDT
```
Response:
```json
{
  "symbol": "XAUUSDT",
  "bidPrice": "2650.40",
  "bidQty": "1.5",
  "askPrice": "2650.50",
  "askQty": "2.0",
  "time": 1499827319559
}
```

#### 4. WebSocket - Real-time Book Ticker
```
wss://fstream.binance.com/ws/xauusdt@bookTicker
```
Message format:
```json
{
  "u": 400900217,
  "s": "XAUUSDT",
  "b": "2650.40",
  "B": "1.5",
  "a": "2650.50",
  "A": "2.0"
}
```

#### 5. Account Information
```
GET /fapi/v2/account
Headers: X-MBX-APIKEY: {api_key}
Params: timestamp, signature
```
Response (key fields):
```json
{
  "totalWalletBalance": "10000.00",
  "totalUnrealizedProfit": "150.50",
  "totalMarginBalance": "10150.50",
  "availableBalance": "8500.00",
  "assets": [
    {
      "asset": "USDT",
      "walletBalance": "10000.00",
      "unrealizedProfit": "150.50",
      "marginBalance": "10150.50",
      "availableBalance": "8500.00"
    }
  ]
}
```

#### 6. Position Information
```
GET /fapi/v2/positionRisk
Headers: X-MBX-APIKEY: {api_key}
Params: timestamp, signature
```
Response:
```json
[
  {
    "symbol": "XAUUSDT",
    "positionAmt": "0.5",
    "entryPrice": "2645.00",
    "markPrice": "2650.50",
    "unRealizedProfit": "2.75",
    "liquidationPrice": "2400.00",
    "leverage": "10",
    "marginType": "cross",
    "isolatedMargin": "0.00",
    "positionSide": "BOTH"
  }
]
```

#### 7. Place Order
```
POST /fapi/v1/order
Headers: X-MBX-APIKEY: {api_key}
Params:
  symbol: XAUUSDT
  side: BUY/SELL
  type: LIMIT/MARKET
  quantity: 0.1
  price: 2650.50 (for LIMIT)
  timeInForce: GTC (for LIMIT)
  timestamp: {timestamp}
  signature: {signature}
```
Response:
```json
{
  "orderId": 123456789,
  "symbol": "XAUUSDT",
  "status": "NEW",
  "clientOrderId": "myOrder1",
  "price": "2650.50",
  "avgPrice": "0.00",
  "origQty": "0.1",
  "executedQty": "0",
  "cumQty": "0",
  "cumQuote": "0",
  "timeInForce": "GTC",
  "type": "LIMIT",
  "side": "BUY"
}
```

#### 8. Query Order Status
```
GET /fapi/v1/order
Headers: X-MBX-APIKEY: {api_key}
Params:
  symbol: XAUUSDT
  orderId: 123456789
  timestamp: {timestamp}
  signature: {signature}
```

#### 9. Cancel Order
```
DELETE /fapi/v1/order
Headers: X-MBX-APIKEY: {api_key}
Params:
  symbol: XAUUSDT
  orderId: 123456789
  timestamp: {timestamp}
  signature: {signature}
```

#### 10. Get Income History (P&L)
```
GET /fapi/v1/income
Headers: X-MBX-APIKEY: {api_key}
Params:
  incomeType: REALIZED_PNL
  startTime: {timestamp}
  endTime: {timestamp}
  timestamp: {timestamp}
  signature: {signature}
```

#### 11. Get Funding Rate
```
GET /fapi/v1/fundingRate?symbol=XAUUSDT
```
Response:
```json
[
  {
    "symbol": "XAUUSDT",
    "fundingRate": "0.0001",
    "fundingTime": 1499827319559
  }
]
```

---

## Bybit V5 API

### Base URLs
- REST: `https://api.bybit.com`
- WebSocket: `wss://stream.bybit.com/v5/public/linear`
- Testnet REST: `https://api-testnet.bybit.com`

### Authentication
```python
import hmac
import hashlib
import time

def sign_request(params, secret_key):
    # V5 uses different signing method
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"

    param_str = timestamp + api_key + recv_window + params
    signature = hmac.new(
        secret_key.encode('utf-8'),
        param_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature, timestamp, recv_window
```

### Key Endpoints for Hustle System

#### 1. Market Data - Tickers
```
GET /v5/market/tickers?category=linear&symbol=XAUUSDT
```
Response:
```json
{
  "retCode": 0,
  "retMsg": "OK",
  "result": {
    "category": "linear",
    "list": [
      {
        "symbol": "XAUUSDT",
        "lastPrice": "2650.50",
        "bid1Price": "2650.40",
        "bid1Size": "1.5",
        "ask1Price": "2650.50",
        "ask1Size": "2.0",
        "turnover24h": "1000000.00",
        "volume24h": "377.00"
      }
    ]
  }
}
```

**Note**: For MT5 accounts, check if symbol should be `XAUUSD` or `XAUUSD.s`

#### 2. WebSocket - Real-time Ticker
```
wss://stream.bybit.com/v5/public/linear
Subscribe message:
{
  "op": "subscribe",
  "args": ["tickers.XAUUSDT"]
}
```

#### 3. Wallet Balance (Account Assets)
```
GET /v5/account/wallet-balance?accountType=UNIFIED
Headers:
  X-BAPI-API-KEY: {api_key}
  X-BAPI-TIMESTAMP: {timestamp}
  X-BAPI-SIGN: {signature}
  X-BAPI-RECV-WINDOW: 5000
```
Response:
```json
{
  "retCode": 0,
  "retMsg": "OK",
  "result": {
    "list": [
      {
        "accountType": "UNIFIED",
        "totalEquity": "10150.50",
        "totalWalletBalance": "10000.00",
        "totalMarginBalance": "10150.50",
        "totalAvailableBalance": "8500.00",
        "coin": [
          {
            "coin": "USDT",
            "equity": "10150.50",
            "walletBalance": "10000.00",
            "availableToWithdraw": "8500.00",
            "unrealisedPnl": "150.50"
          }
        ]
      }
    ]
  }
}
```

**For MT5 accounts**: May need to use `accountType=CONTRACT` or check Bybit docs

#### 4. Position Information
```
GET /v5/position/list?category=linear&symbol=XAUUSDT
Headers: (same as above)
```
Response:
```json
{
  "retCode": 0,
  "retMsg": "OK",
  "result": {
    "list": [
      {
        "symbol": "XAUUSDT",
        "side": "Buy",
        "size": "0.5",
        "avgPrice": "2645.00",
        "positionValue": "1322.50",
        "unrealisedPnl": "2.75",
        "leverage": "10",
        "markPrice": "2650.50",
        "liqPrice": "2400.00"
      }
    ]
  }
}
```

#### 5. Place Order
```
POST /v5/order/create
Headers: (same as above)
Body:
{
  "category": "linear",
  "symbol": "XAUUSDT",
  "side": "Buy",
  "orderType": "Limit",
  "qty": "0.1",
  "price": "2650.50",
  "timeInForce": "GTC"
}
```
Response:
```json
{
  "retCode": 0,
  "retMsg": "OK",
  "result": {
    "orderId": "1234567890",
    "orderLinkId": "myOrder1"
  }
}
```

#### 6. Query Order
```
GET /v5/order/realtime?category=linear&symbol=XAUUSDT&orderId=1234567890
Headers: (same as above)
```

#### 7. Cancel Order
```
POST /v5/order/cancel
Headers: (same as above)
Body:
{
  "category": "linear",
  "symbol": "XAUUSDT",
  "orderId": "1234567890"
}
```

#### 8. Transaction Log (P&L)
```
GET /v5/account/transaction-log?accountType=UNIFIED&category=linear
Headers: (same as above)
```

#### 9. Fee Rate
```
GET /v5/account/fee-rate?category=linear&symbol=XAUUSDT
Headers: (same as above)
```

---

## MT5 Integration Options

### Option 1: Python MetaTrader5 Package (Recommended for Testing)

```python
import MetaTrader5 as mt5

# Initialize connection
if not mt5.initialize():
    print("MT5 initialization failed")
    quit()

# Get account info
account_info = mt5.account_info()
print(f"Balance: {account_info.balance}")
print(f"Equity: {account_info.equity}")
print(f"Margin: {account_info.margin}")

# Get symbol info
symbol_info = mt5.symbol_info("XAUUSD")
print(f"Bid: {symbol_info.bid}")
print(f"Ask: {symbol_info.ask}")

# Get tick data
tick = mt5.symbol_info_tick("XAUUSD")
print(f"Bid: {tick.bid}, Ask: {tick.ask}, Time: {tick.time}")

# Place order
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": "XAUUSD",
    "volume": 0.1,
    "type": mt5.ORDER_TYPE_BUY,
    "price": mt5.symbol_info_tick("XAUUSD").ask,
    "deviation": 10,
    "magic": 234000,
    "comment": "python script open",
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
}

result = mt5.order_send(request)
print(f"Order result: {result}")

# Get positions
positions = mt5.positions_get(symbol="XAUUSD")
for pos in positions:
    print(f"Position: {pos.ticket}, Volume: {pos.volume}, Profit: {pos.profit}")

# Shutdown
mt5.shutdown()
```

**Limitations**:
- Requires MT5 terminal running on same machine
- Not suitable for cloud deployment without VPS with MT5

### Option 2: Bybit V5 API with MT5 Account

**Check if Bybit allows V5 API access to MT5 accounts**:
1. Log into Bybit with MT5 account credentials
2. Generate API key from account settings
3. Test if `/v5/market/tickers` returns XAUUSD data
4. Test if `/v5/account/wallet-balance` returns MT5 account balance

If this works, you can use standard V5 API endpoints with MT5 account credentials.

### Option 3: Custom MT5 Bridge (Advanced)

Build an Expert Advisor (EA) in MQL5 that:
1. Runs on MT5 terminal
2. Exposes REST API via HTTP server
3. Pushes tick data to your backend via WebSocket
4. Receives order commands from your backend

**Not recommended for MVP** - too complex.

---

## Python Client Examples

### Binance Client Wrapper

```python
import aiohttp
import hmac
import hashlib
import time
from typing import Dict, Any

class BinanceFuturesClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"

    def _sign(self, params: Dict[str, Any]) -> str:
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _request(self, method: str, endpoint: str, signed: bool = False, **kwargs):
        url = f"{self.base_url}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key} if signed else {}

        if signed:
            params = kwargs.get('params', {})
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._sign(params)
            kwargs['params'] = params

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, **kwargs) as resp:
                return await resp.json()

    async def get_server_time(self):
        return await self._request('GET', '/fapi/v1/time')

    async def get_book_ticker(self, symbol: str):
        return await self._request('GET', '/fapi/v1/ticker/bookTicker', params={'symbol': symbol})

    async def get_account(self):
        return await self._request('GET', '/fapi/v2/account', signed=True)

    async def get_position_risk(self, symbol: str = None):
        params = {'symbol': symbol} if symbol else {}
        return await self._request('GET', '/fapi/v2/positionRisk', signed=True, params=params)

    async def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None):
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity
        }
        if order_type == 'LIMIT':
            params['price'] = price
            params['timeInForce'] = 'GTC'

        return await self._request('POST', '/fapi/v1/order', signed=True, params=params)

    async def cancel_order(self, symbol: str, order_id: int):
        params = {'symbol': symbol, 'orderId': order_id}
        return await self._request('DELETE', '/fapi/v1/order', signed=True, params=params)

    async def get_order(self, symbol: str, order_id: int):
        params = {'symbol': symbol, 'orderId': order_id}
        return await self._request('GET', '/fapi/v1/order', signed=True, params=params)
```

### Bybit V5 Client Wrapper

```python
import aiohttp
import hmac
import hashlib
import time
from typing import Dict, Any

class BybitV5Client:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"

    def _sign(self, timestamp: str, params: str) -> str:
        recv_window = "5000"
        param_str = timestamp + self.api_key + recv_window + params
        return hmac.new(
            self.api_secret.encode('utf-8'),
            param_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _request(self, method: str, endpoint: str, signed: bool = False, **kwargs):
        url = f"{self.base_url}{endpoint}"
        timestamp = str(int(time.time() * 1000))
        headers = {}

        if signed:
            params = kwargs.get('json', {})
            param_str = str(params) if params else ""
            signature = self._sign(timestamp, param_str)

            headers = {
                "X-BAPI-API-KEY": self.api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": signature,
                "X-BAPI-RECV-WINDOW": "5000"
            }

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, **kwargs) as resp:
                return await resp.json()

    async def get_tickers(self, category: str, symbol: str):
        params = {'category': category, 'symbol': symbol}
        return await self._request('GET', '/v5/market/tickers', params=params)

    async def get_wallet_balance(self, account_type: str = "UNIFIED"):
        params = {'accountType': account_type}
        return await self._request('GET', '/v5/account/wallet-balance', signed=True, params=params)

    async def get_positions(self, category: str, symbol: str = None):
        params = {'category': category}
        if symbol:
            params['symbol'] = symbol
        return await self._request('GET', '/v5/position/list', signed=True, params=params)

    async def place_order(self, category: str, symbol: str, side: str, order_type: str, qty: str, price: str = None):
        data = {
            'category': category,
            'symbol': symbol,
            'side': side,
            'orderType': order_type,
            'qty': qty
        }
        if order_type == 'Limit':
            data['price'] = price
            data['timeInForce'] = 'GTC'

        return await self._request('POST', '/v5/order/create', signed=True, json=data)

    async def cancel_order(self, category: str, symbol: str, order_id: str):
        data = {
            'category': category,
            'symbol': symbol,
            'orderId': order_id
        }
        return await self._request('POST', '/v5/order/cancel', signed=True, json=data)

    async def get_order(self, category: str, symbol: str, order_id: str):
        params = {
            'category': category,
            'symbol': symbol,
            'orderId': order_id
        }
        return await self._request('GET', '/v5/order/realtime', signed=True, params=params)
```

---

## Testing Checklist

### Before Production Deployment

- [ ] Test Binance testnet API access
- [ ] Test Bybit testnet API access (if available)
- [ ] Verify MT5 account API access method
- [ ] Test order placement on both platforms
- [ ] Test order cancellation
- [ ] Test WebSocket connections stability
- [ ] Verify spread calculation accuracy
- [ ] Test chase order logic with paper trading
- [ ] Verify account balance calculations
- [ ] Test risk alert system
- [ ] Load test WebSocket with multiple clients
- [ ] Test database connection pooling
- [ ] Verify Redis caching performance
- [ ] Test system behavior during network issues
- [ ] Verify time synchronization accuracy

---

**Document Version**: 1.0
**Last Updated**: 2026-02-18
