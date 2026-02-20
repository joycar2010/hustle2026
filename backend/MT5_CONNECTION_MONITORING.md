# MT5 Connection Monitoring and Auto-Reconnection Strategy

## Overview
Implemented automatic connection monitoring and reconnection strategy for Bybit MT5 market data feed to handle network issues, connection timeouts, and service interruptions.

## Features

### 1. Connection Health Monitoring
- **Last Request Tracking**: Monitors timestamp of last successful MT5 request
- **Timeout Detection**: Marks connection as unhealthy if no activity for 30 seconds
- **Connection State**: Tracks connected/disconnected status

### 2. Automatic Reconnection
- **Exponential Backoff**: Delays between reconnection attempts increase exponentially
  - Initial delay: 5 seconds
  - Maximum delay: 60 seconds
  - Formula: `delay = min(5 * (2 ^ failures), 60)`
- **Failure Tracking**: Counts consecutive connection failures
- **Max Failures**: Stops attempting after 5 consecutive failures (configurable)

### 3. Connection Recovery
- **Auto-reconnect on Failure**: Automatically attempts to reconnect when requests fail
- **Graceful Degradation**: Returns None on failure instead of crashing
- **Connection Reset**: Resets failure counter on successful connection

## API Endpoints

### GET /api/v1/market/connection/status
Get current MT5 connection status and health information.

**Response:**
```json
{
  "mt5": {
    "connected": true,
    "healthy": true,
    "connection_failures": 0,
    "max_failures": 5,
    "last_successful_request": "2026-02-20T13:10:54.436902",
    "last_connection_attempt": "2026-02-20T13:10:50.123456",
    "seconds_since_last_request": 4.31
  },
  "service_running": true
}
```

### POST /api/v1/market/connection/reset
Reset the connection failure counter (useful for manual recovery).

**Response:**
```json
{
  "message": "Connection failure counter reset successfully",
  "status": { ... }
}
```

### POST /api/v1/market/connection/reconnect
Force MT5 reconnection immediately.

**Response:**
```json
{
  "success": true,
  "message": "Reconnection successful",
  "status": { ... }
}
```

## Implementation Details

### MT5Client Enhancements

#### New Properties
- `last_successful_request`: Timestamp of last successful MT5 request
- `last_connection_attempt`: Timestamp of last connection attempt
- `connection_failures`: Counter for consecutive failures
- `max_connection_failures`: Maximum allowed failures (default: 5)
- `reconnect_delay`: Initial reconnection delay (default: 5s)
- `max_reconnect_delay`: Maximum reconnection delay (default: 60s)
- `connection_timeout`: Timeout for stale connections (default: 30s)

#### New Methods
- `is_connection_healthy()`: Check if connection is healthy
- `ensure_connection()`: Ensure connection is active, reconnect if needed
- `get_connection_status()`: Get detailed connection status
- `reset_connection_failures()`: Reset failure counter
- `_calculate_reconnect_delay()`: Calculate delay with exponential backoff
- `_should_attempt_reconnect()`: Check if reconnection should be attempted

### Modified Methods
- `connect()`: Now tracks connection attempts and failures
- `get_tick()`: Uses `ensure_connection()` and updates last request timestamp
- `get_account_info()`: Uses `ensure_connection()` and updates last request timestamp

## Usage Example

### Check Connection Status
```python
from app.services.realtime_market_service import market_data_service

mt5_client = market_data_service.mt5_client
status = mt5_client.get_connection_status()

if not status["healthy"]:
    print(f"Connection unhealthy: {status}")
```

### Force Reconnection
```python
mt5_client.disconnect()
mt5_client.reset_connection_failures()
success = mt5_client.connect()
```

### Get Market Data (Auto-reconnects)
```python
# Will automatically reconnect if connection is lost
tick = mt5_client.get_tick("XAUUSD.s")
if tick:
    print(f"Bid: {tick['bid']}, Ask: {tick['ask']}")
```

## Configuration

Edit `d:\git\hustle2026\backend\app\services\mt5_client.py` to adjust:

```python
# Connection monitoring
self.reconnect_delay = 5  # Initial delay in seconds
self.max_reconnect_delay = 60  # Maximum delay in seconds
self.connection_timeout = 30  # Timeout for stale connections
self.max_connection_failures = 5  # Max consecutive failures
```

## Monitoring and Alerts

### Frontend Integration
Add a connection status indicator in the trading dashboard:

```javascript
// Check MT5 connection status
const checkMT5Status = async () => {
  const response = await api.get('/api/v1/market/connection/status')
  const { mt5 } = response.data

  if (!mt5.healthy) {
    showAlert('MT5 connection unhealthy', 'warning')
  }
}

// Check every 10 seconds
setInterval(checkMT5Status, 10000)
```

### Logging
All connection events are logged:
- Connection attempts
- Connection failures
- Reconnection delays
- Health check failures

Check logs at: `d:\git\hustle2026\backend\backend.log`

## Troubleshooting

### Connection Keeps Failing
1. Check MT5 credentials in `.env` file
2. Verify MT5 terminal is running
3. Check network connectivity
4. Reset failure counter: `POST /api/v1/market/connection/reset`

### Connection Appears Stale
1. Check last successful request timestamp
2. Force reconnection: `POST /api/v1/market/connection/reconnect`
3. Restart the backend service

### Max Failures Reached
1. Check MT5 terminal status
2. Verify credentials
3. Reset failure counter
4. Increase `max_connection_failures` if needed

## Benefits

1. **Reliability**: Automatically recovers from temporary network issues
2. **Resilience**: Handles MT5 terminal restarts gracefully
3. **Monitoring**: Provides detailed connection health information
4. **Control**: Manual override options for troubleshooting
5. **Performance**: Exponential backoff prevents overwhelming the MT5 server

## Next Steps

1. Add frontend connection status indicator
2. Implement connection alerts/notifications
3. Add metrics tracking (uptime, failure rate)
4. Consider WebSocket for real-time status updates
