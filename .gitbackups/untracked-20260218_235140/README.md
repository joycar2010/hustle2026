# Hustle XAU Arbitrage System

Cross-platform arbitrage trading system for Binance XAUUSDT perpetual futures and Bybit TradFi MT5 XAUUSD.s.

## System Overview

This system enables automated arbitrage trading between:
- **Binance**: XAUUSDT perpetual futures
- **Bybit TradFi MT5**: XAUUSD.s

### Key Features

- Multi-user support (3-5 users)
- Multi-account management (Binance + Bybit MT5)
- Real-time market data streaming
- Forward and reverse arbitrage strategies
- Ladder order execution
- MT5 stuck detection and risk monitoring
- WebSocket-based live updates
- Comprehensive account dashboard

## Architecture

- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL
- **Cache**: Redis
- **Frontend**: Vue 3 + TailwindCSS (planned)
- **Deployment**: Docker + Docker Compose

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Docker & Docker Compose (optional)

### Option 1: Docker Compose (Recommended)

1. Start services:
```bash
docker-compose up -d
```

2. Install backend dependencies:
```bash
cd backend
pip install -r requirements.txt
```

3. Set up environment:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Run migrations:
```bash
alembic upgrade head
```

5. Initialize platform data:
```bash
python -m app.scripts.init_platforms
```

6. Start backend:
```bash
uvicorn app.main:app --reload
```

### Option 2: Manual Setup

1. Install and start PostgreSQL and Redis

2. Create database:
```bash
createdb hustle_db
```

3. Follow steps 2-6 from Option 1

## API Documentation

Access the interactive API documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

```
hustle2026/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── api/v1/         # API endpoints
│   │   ├── core/           # Configuration
│   │   ├── models/         # Database models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # Business logic
│   │   └── main.py         # App entry point
│   ├── alembic/            # Database migrations
│   ├── requirements.txt
│   └── README.md
├── frontend/               # Vue 3 frontend (planned)
├── docker-compose.yml      # Docker services
├── IMPLEMENTATION_PLAN.md  # Detailed implementation guide
└── API_INTEGRATION_GUIDE.md # API integration reference
```

## Development Status

### Phase 1: Foundation ✅ (Completed)
- [x] Project structure
- [x] Database models
- [x] JWT authentication
- [x] User management API
- [x] Account management API
- [x] Database migrations

### Phase 2: Market Data Integration ✅ (Completed)
- [x] Binance Futures client
- [x] Bybit V5 client
- [x] Market data service
- [x] WebSocket push service
- [x] Redis caching
- [x] Spread calculation
- [x] Background streaming

### Phase 3: Account Data Integration ✅ (Completed)
- [x] Account data fetching service
- [x] Account balance endpoints
- [x] Position tracking endpoints
- [x] P&L calculation
- [x] Multi-account aggregation
- [x] Comprehensive dashboard API

### Phase 4: Strategy Engine ✅ (Completed)
- [x] Order executor service
- [x] Forward arbitrage strategy
- [x] Reverse arbitrage strategy
- [x] Chase order logic (3-second retry)
- [x] Order state management
- [x] Strategy execution API

### Phase 5: Risk Control ✅ (Completed)
- [x] MT5 stuck detection
- [x] Account risk monitoring
- [x] Position limit checks
- [x] Emergency stop mechanism
- [x] Risk alert system
- [x] WebSocket risk notifications
- [x] Comprehensive risk validation

### Phase 6: Automated Strategies ✅ (Completed)
- [x] Automatic strategy execution
- [x] Position monitoring
- [x] Auto-close logic
- [x] Ladder order strategy
- [x] Spread-based triggers
- [x] Risk-based position sizing
- [x] Automation API endpoints

### Phase 7-8: See IMPLEMENTATION_PLAN.md

## Configuration

Key environment variables in `.env`:

```bash
# Database
DATABASE_URL=postgresql://hustle_user:hustle_password@localhost:5432/hustle_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=your-secret-key-change-this

# API Endpoints
BINANCE_API_BASE=https://fapi.binance.com
BYBIT_API_BASE=https://api.bybit.com
```

## Testing

Run tests:
```bash
cd backend
pytest
```

With coverage:
```bash
pytest --cov=app --cov-report=html
```

## Documentation

- [Implementation Plan](IMPLEMENTATION_PLAN.md) - 15-week development roadmap
- [API Integration Guide](API_INTEGRATION_GUIDE.md) - Binance/Bybit API reference
- [Backend README](backend/README.md) - Backend-specific documentation

## Security Notes

- API keys are stored encrypted in the database
- JWT tokens for authentication
- CORS configured for known origins
- Rate limiting implemented
- Input validation with Pydantic

## Risk Disclaimer

This system involves real financial trading. Before production:
- Test extensively with testnet/paper trading
- Start with small position sizes
- Monitor closely
- Understand funding fees and slippage
- Comply with local regulations

## License

Proprietary - All rights reserved

## Support

For questions or issues, refer to the documentation or contact the development team.
