# Hustle XAU Arbitrage System - Implementation Plan

## Executive Summary

This document provides a practical implementation plan for the Hustle XAU arbitrage system, designed for Binance XAUUSDT perpetual futures and Bybit TradFi MT5 XAUUSD.s cross-platform arbitrage.

## 1. Architecture Validation

### ✅ Strengths
- **Microservices separation**: Clear module boundaries (users, accounts, market, strategy, risk)
- **Database design**: Comprehensive schema with MT5-specific fields
- **Caching strategy**: Redis for high-frequency market data
- **Real-time communication**: WebSocket for live updates

### ⚠️ Critical Issues to Address

#### 1.1 Bybit MT5 API Reality Check
**Problem**: Bybit TradFi MT5 doesn't expose standard REST/WebSocket APIs like crypto exchanges.

**Solutions**:
- **Option A**: Use Python `MetaTrader5` package to connect to local MT5 terminal
  - Requires MT5 terminal running on server
  - Access via `MetaTrader5.symbol_info_tick()` for quotes
  - Limited to server where MT5 is installed

- **Option B**: Check if Bybit V5 API supports MT5 account queries
  - Use `/v5/market/tickers` with MT5 account credentials
  - Verify if `XAUUSD.s` is accessible via V5 API

- **Option C**: Build MT5 bridge service
  - MT5 Expert Advisor (EA) pushes data to your API
  - More complex but more flexible

**Recommendation**: Start with Option B (V5 API), fallback to Option A if needed.

#### 1.2 Time Synchronization Strategy
**Current design**: Use Binance `/fapi/v1/time` for calibration.

**Enhanced approach**:
```python
# Sync time on startup and every 5 minutes
server_time_offset = binance_time - local_time
# Apply offset to all order timestamps
order_timestamp = int(time.time() * 1000) + server_time_offset
```

**Add monitoring**:
- Track latency to both platforms (Binance, Bybit)
- Alert if latency > 200ms (affects arbitrage profitability)
- Log time drift for debugging

#### 1.3 Order Execution Race Conditions
**Problem**: Chase order logic (3-second retry) can create duplicate orders without proper locking.

**Solution**: Use Redis distributed locks
```python
# Pseudo-code
lock_key = f"order_lock:{user_id}:{symbol}:{side}"
with redis_lock(lock_key, timeout=10):
    # Check existing orders
    # Place new order
    # Update state
```

#### 1.4 Account Data API Mapping

**Bybit V5 API** (for MT5 accounts):
- Total assets: `/v5/account/wallet-balance` → `equity`
- Available: `/v5/account/wallet-balance` → `availableToWithdraw`
- Positions: `/v5/position/list` → filter by `symbol=XAUUSD`
- Funding fee: `/v5/account/fee-rate` (check if MT5 accounts have funding)

**Binance Futures API**:
- Total assets: `/fapi/v2/account` → `totalWalletBalance`
- Available: `/fapi/v2/account` → `availableBalance`
- Positions: `/fapi/v2/positionRisk` → filter `positionAmt != 0`
- Funding fee: `/fapi/v1/fundingRate` for current rate

## 2. Project Structure

```
hustle2026/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── core/
│   │   │   ├── config.py           # Settings (DB, Redis, API keys)
│   │   │   ├── security.py         # JWT auth
│   │   │   └── database.py         # PostgreSQL connection
│   │   ├── models/                 # SQLAlchemy models
│   │   │   ├── user.py
│   │   │   ├── account.py
│   │   │   ├── order.py
│   │   │   ├── strategy.py
│   │   │   └── risk_alert.py
│   │   ├── schemas/                # Pydantic schemas
│   │   │   ├── user.py
│   │   │   ├── account.py
│   │   │   └── market.py
│   │   ├── api/                    # API routes
│   │   │   ├── v1/
│   │   │   │   ├── users.py
│   │   │   │   ├── accounts.py
│   │   │   │   ├── market.py
│   │   │   │   ├── strategies.py
│   │   │   │   └── orders.py
│   │   ├── services/               # Business logic
│   │   │   ├── market_service.py   # Market data aggregation
│   │   │   ├── binance_client.py   # Binance API wrapper
│   │   │   ├── bybit_client.py     # Bybit V5 API wrapper
│   │   │   ├── mt5_bridge.py       # MT5 connection (if needed)
│   │   │   ├── strategy_engine.py  # Arbitrage logic
│   │   │   ├── order_executor.py   # Order placement & chase
│   │   │   └── risk_monitor.py     # Risk control
│   │   ├── websocket/
│   │   │   ├── manager.py          # WebSocket connection manager
│   │   │   └── handlers.py         # Message handlers
│   │   └── tasks/                  # Background tasks
│   │       ├── market_data.py      # Market data collection
│   │       └── risk_check.py       # Periodic risk checks
│   ├── alembic/                    # Database migrations
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Dashboard.vue       # Main dashboard
│   │   │   ├── MarketPanel.vue     # Real-time prices & spread
│   │   │   ├── AccountPanel.vue    # Account assets & positions
│   │   │   ├── StrategyPanel.vue   # Strategy controls
│   │   │   └── RiskAlert.vue       # Risk notifications
│   │   ├── services/
│   │   │   ├── api.js              # API client
│   │   │   └── websocket.js        # WebSocket client
│   │   ├── store/                  # Vuex/Pinia state
│   │   └── App.vue
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

## 3. Implementation Phases

### Phase 1: Foundation (Week 1-2)
**Goal**: Set up infrastructure and basic API

**Tasks**:
1. Initialize FastAPI project with PostgreSQL + Redis
2. Implement database models (users, accounts, platforms)
3. Create authentication (JWT)
4. Build user management API (`/api/v1/users/*`)
5. Build account management API (`/api/v1/accounts/*`)
6. Write database migration scripts (Alembic)

**Deliverables**:
- User registration/login working
- Account CRUD operations
- API documentation (auto-generated by FastAPI)

### Phase 2: Market Data Integration (Week 3-4)
**Goal**: Real-time market data from both platforms

**Tasks**:
1. Implement Binance Futures client
   - REST API wrapper (`/fapi/v1/ticker/price`, `/fapi/v1/time`)
   - WebSocket subscription (`<symbol>@bookTicker`)
2. Implement Bybit client
   - Test V5 API access to MT5 accounts
   - REST API wrapper (`/v5/market/tickers`)
   - WebSocket subscription (if available)
3. Build market data service
   - Aggregate bid/ask from both platforms
   - Calculate spread in real-time
   - Cache in Redis (TTL: 1 second)
4. Create market data API (`/api/v1/market/quotes`)
5. Implement WebSocket push service
   - Broadcast market data to connected clients
   - Push format: `{type: 'market', data: {binance: {...}, bybit: {...}, spread: ...}}`

**Deliverables**:
- Real-time market data streaming
- Spread calculation working
- WebSocket clients receiving updates

### Phase 3: Account Data Integration (Week 5)
**Goal**: Fetch and display account information

**Tasks**:
1. Implement Binance account data fetching
   - `/fapi/v2/account` for balance
   - `/fapi/v2/positionRisk` for positions
   - `/fapi/v1/income` for daily P&L
2. Implement Bybit account data fetching
   - `/v5/account/wallet-balance` for balance
   - `/v5/position/list` for positions
   - `/v5/account/transaction-log` for P&L
3. Build account dashboard API
   - `/api/v1/accounts/{account_id}/balance`
   - `/api/v1/accounts/{account_id}/positions`
   - `/api/v1/accounts/{account_id}/pnl`
4. Aggregate multi-account data for user view

**Deliverables**:
- Account panel showing all required metrics
- Multi-account aggregation working

### Phase 4: Strategy Engine (Week 6-8)
**Goal**: Implement arbitrage strategies

**Tasks**:
1. Build order executor
   - Place orders on Binance/Bybit
   - Handle API errors and retries
   - Implement idempotency
2. Implement forward arbitrage strategy
   - Monitor spread for entry condition
   - Place dual orders (sell Bybit, buy Binance)
   - Implement 3-second check + chase logic
   - Close positions when spread narrows
3. Implement reverse arbitrage strategy
   - Monitor spread for entry condition
   - Place dual orders (buy Bybit, sell Binance)
   - Implement chase logic
   - Close positions
4. Implement ladder order strategy
   - Batch order placement based on spread levels
   - Track multiple open positions
5. Add strategy configuration API
   - `/api/v1/strategies/configs`
   - Enable/disable strategies per user
6. Store order records in database

**Deliverables**:
- Working arbitrage strategies
- Order history tracking
- Strategy control panel

### Phase 5: Risk Control (Week 9)
**Goal**: Implement risk monitoring and alerts

**Tasks**:
1. Build risk monitor service
   - Check MT5 data staleness (stuck detection)
   - Monitor account risk ratio
   - Detect abnormal spreads
   - Check position limits
2. Implement alert system
   - Store alerts in database
   - Push via WebSocket to frontend
   - Auto-expire after 5 minutes
3. Add emergency stop mechanism
   - Pause all strategies on critical alerts
   - Require manual resume

**Deliverables**:
- Risk alerts working
- MT5 stuck detection functional
- Emergency stop tested

### Phase 6: Frontend Development (Week 10-12)
**Goal**: Build user interface

**Tasks**:
1. Set up Vue 3 + TailwindCSS project
2. Implement authentication pages (login/register)
3. Build main dashboard
   - Market panel (real-time prices, spread chart)
   - Account panel (assets, positions, P&L)
   - Strategy control panel
   - Order history table
4. Implement WebSocket client
   - Connect to backend WebSocket
   - Update UI in real-time
5. Add risk alert notifications (bottom-right toast)
6. Responsive design for different screen sizes

**Deliverables**:
- Fully functional web interface
- Real-time data updates
- Mobile-friendly design

### Phase 7: Testing & Optimization (Week 13-14)
**Goal**: Ensure system reliability

**Tasks**:
1. Write unit tests for core logic
2. Integration tests for API endpoints
3. Load testing for WebSocket connections
4. Simulate market conditions and test strategies
5. Optimize database queries
6. Add monitoring (Prometheus + Grafana)
7. Set up logging (structured logs)

**Deliverables**:
- Test coverage > 70%
- Performance benchmarks documented
- Monitoring dashboard

### Phase 8: Deployment (Week 15)
**Goal**: Deploy to production

**Tasks**:
1. Create Docker images for backend/frontend
2. Write docker-compose.yml for local deployment
3. Set up production environment (AWS/GCP/Azure)
4. Configure SSL certificates
5. Set up database backups
6. Deploy and smoke test
7. Write deployment documentation

**Deliverables**:
- System running in production
- Deployment guide
- Backup strategy documented

## 4. Critical Implementation Details

### 4.1 Chase Order Logic (Pseudo-code)

```python
async def execute_arbitrage_order(user_id, strategy_type, quantity):
    # Step 1: Place initial orders
    binance_order = await place_binance_order(...)
    bybit_order = await place_bybit_order(...)

    # Step 2: Wait 3 seconds and check fills
    await asyncio.sleep(3)
    binance_filled = await check_order_status(binance_order.id)
    bybit_filled = await check_order_status(bybit_order.id)

    # Step 3: Chase unfilled orders
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        if not binance_filled:
            await cancel_order(binance_order.id)
            # Use market order for priority fill
            binance_order = await place_binance_order(..., order_type='MARKET')
            await asyncio.sleep(3)
            binance_filled = await check_order_status(binance_order.id)

        if not bybit_filled:
            await cancel_order(bybit_order.id)
            bybit_order = await place_bybit_order(..., order_type='MARKET')
            await asyncio.sleep(3)
            bybit_filled = await check_order_status(bybit_order.id)

        if binance_filled and bybit_filled:
            break

        retry_count += 1

    # Step 4: Handle partial success
    if not (binance_filled and bybit_filled):
        await send_risk_alert(user_id, "Partial fill detected")
        # Decide: close filled position or keep trying
```

### 4.2 MT5 Stuck Detection

```python
# In market data service
class MT5StuckDetector:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.key_prefix = "mt5_stuck_counter"

    async def check_price_update(self, symbol, current_price, timestamp):
        key = f"{self.key_prefix}:{symbol}"
        last_data = await self.redis.get(key)

        if last_data:
            last_price, last_time, counter = json.loads(last_data)

            # If price hasn't changed and time diff > 1 second
            if last_price == current_price and (timestamp - last_time) > 1:
                counter += 1
            else:
                counter = 0

            # Check threshold
            threshold = await get_user_mt5_threshold()  # From strategy_configs
            if counter >= threshold:
                await send_risk_alert("MT5 data stuck detected")
                await pause_all_strategies()

        # Update Redis
        await self.redis.set(key, json.dumps([current_price, timestamp, counter]))
```

### 4.3 Spread Calculation

```python
def calculate_spread(binance_bid, binance_ask, bybit_bid, bybit_ask):
    """
    Forward arbitrage spread (long Binance):
    - Entry: bybit_ask - binance_bid (positive = profitable)
    - Exit: binance_ask - bybit_bid

    Reverse arbitrage spread (long Bybit):
    - Entry: binance_ask - bybit_bid (negative = profitable)
    - Exit: bybit_ask - binance_bid
    """
    forward_entry_spread = bybit_ask - binance_bid
    forward_exit_spread = binance_ask - bybit_bid

    reverse_entry_spread = binance_ask - bybit_bid
    reverse_exit_spread = bybit_ask - binance_bid

    return {
        'forward': {
            'entry': forward_entry_spread,
            'exit': forward_exit_spread
        },
        'reverse': {
            'entry': reverse_entry_spread,
            'exit': reverse_exit_spread
        },
        'timestamp': int(time.time() * 1000)
    }
```

## 5. Database Migration Scripts

### Initial Migration (Alembic)

```python
# alembic/versions/001_initial_schema.py
def upgrade():
    # Create users table
    op.create_table(
        'users',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('email', sa.String(100), unique=True),
        sa.Column('create_time', sa.TIMESTAMP, server_default=sa.func.now()),
        sa.Column('update_time', sa.TIMESTAMP, server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean, default=True)
    )

    # Create platforms table
    op.create_table(
        'platforms',
        sa.Column('platform_id', sa.SmallInteger, primary_key=True),
        sa.Column('platform_name', sa.String(20), nullable=False),
        sa.Column('api_base_url', sa.String(100), nullable=False),
        sa.Column('ws_base_url', sa.String(100), nullable=False),
        sa.Column('account_api_type', sa.String(30), nullable=False),
        sa.Column('market_api_type', sa.String(30), nullable=False)
    )

    # Insert default platforms
    op.execute("""
        INSERT INTO platforms VALUES
        (1, 'Binance', 'https://fapi.binance.com', 'wss://fstream.binance.com',
         'binance_futures', 'binance_futures'),
        (2, 'Bybit', 'https://api.bybit.com', 'wss://stream.bybit.com',
         'bybit_v5', 'bybit_mt5')
    """)

    # Create accounts table with MT5 fields
    op.create_table(
        'accounts',
        sa.Column('account_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.user_id'), nullable=False),
        sa.Column('platform_id', sa.SmallInteger,
                  sa.ForeignKey('platforms.platform_id'), nullable=False),
        sa.Column('account_name', sa.String(50), nullable=False),
        sa.Column('api_key', sa.String(256), nullable=False),
        sa.Column('api_secret', sa.String(256), nullable=False),
        sa.Column('passphrase', sa.String(100)),
        sa.Column('mt5_id', sa.String(100)),
        sa.Column('mt5_server', sa.String(100)),
        sa.Column('mt5_primary_pwd', sa.String(256)),
        sa.Column('is_mt5_account', sa.Boolean, default=False),
        sa.Column('is_default', sa.Boolean, default=False),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('create_time', sa.TIMESTAMP, server_default=sa.func.now()),
        sa.Column('update_time', sa.TIMESTAMP, server_default=sa.func.now())
    )

    # Create other tables (strategy_configs, order_records, etc.)
    # ... (similar structure as documented)
```

## 6. Configuration Management

### Environment Variables (.env)

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/hustle_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Binance API
BINANCE_API_BASE=https://fapi.binance.com
BINANCE_WS_BASE=wss://fstream.binance.com

# Bybit API
BYBIT_API_BASE=https://api.bybit.com
BYBIT_WS_BASE=wss://stream.bybit.com

# System
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

## 7. API Endpoint Summary

### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - User login
- `POST /api/v1/auth/refresh` - Refresh token

### Users
- `GET /api/v1/users/me` - Get current user
- `PUT /api/v1/users/me` - Update current user

### Accounts
- `GET /api/v1/accounts` - List user accounts
- `POST /api/v1/accounts` - Add new account
- `GET /api/v1/accounts/{id}` - Get account details
- `PUT /api/v1/accounts/{id}` - Update account
- `DELETE /api/v1/accounts/{id}` - Delete account
- `GET /api/v1/accounts/{id}/balance` - Get account balance
- `GET /api/v1/accounts/{id}/positions` - Get positions
- `GET /api/v1/accounts/{id}/pnl` - Get P&L

### Market Data
- `GET /api/v1/market/quotes` - Get current quotes (Binance + Bybit)
- `GET /api/v1/market/spread` - Get current spread
- `GET /api/v1/market/spread/history` - Get spread history

### Strategies
- `GET /api/v1/strategies/configs` - List strategy configs
- `POST /api/v1/strategies/configs` - Create strategy config
- `PUT /api/v1/strategies/configs/{id}` - Update strategy config
- `POST /api/v1/strategies/{id}/start` - Start strategy
- `POST /api/v1/strategies/{id}/stop` - Stop strategy

### Orders
- `GET /api/v1/orders` - List orders
- `GET /api/v1/orders/{id}` - Get order details
- `POST /api/v1/orders/cancel/{id}` - Cancel order

### Risk Alerts
- `GET /api/v1/alerts` - List active alerts
- `DELETE /api/v1/alerts/{id}` - Dismiss alert

### WebSocket
- `WS /ws` - WebSocket connection for real-time updates

## 8. Security Considerations

1. **API Key Storage**: Encrypt API keys in database using Fernet or similar
2. **Rate Limiting**: Implement per-user rate limits (100 req/min)
3. **Input Validation**: Validate all user inputs (Pydantic schemas)
4. **SQL Injection**: Use SQLAlchemy ORM (parameterized queries)
5. **CORS**: Restrict to known frontend origins
6. **HTTPS**: Enforce HTTPS in production
7. **Secrets Management**: Use environment variables, never commit secrets

## 9. Monitoring & Logging

### Key Metrics to Track
- API latency (Binance, Bybit)
- Order execution time
- Spread values (min, max, avg)
- Order fill rates
- System uptime
- WebSocket connection count
- Database query performance

### Logging Strategy
```python
import structlog

logger = structlog.get_logger()

# Log format
logger.info("order_placed",
            user_id=user_id,
            platform="binance",
            symbol="XAUUSDT",
            side="buy",
            price=2650.5,
            quantity=0.1)
```

## 10. Next Steps

1. **Validate Bybit MT5 API access** - Test if V5 API works with MT5 accounts
2. **Set up development environment** - PostgreSQL, Redis, Python 3.11+
3. **Start Phase 1 implementation** - Foundation and basic API
4. **Create test accounts** - Binance testnet, Bybit testnet (if available)
5. **Build MVP** - Focus on market data + basic arbitrage first

## 11. Risk Disclaimer

This system involves real financial trading. Before production deployment:
- Test extensively with testnet/paper trading
- Start with small position sizes
- Monitor closely for the first weeks
- Have emergency stop mechanisms
- Understand funding fees and slippage impact
- Comply with local regulations

---

**Document Version**: 1.0
**Last Updated**: 2026-02-18
**Author**: System Architect

