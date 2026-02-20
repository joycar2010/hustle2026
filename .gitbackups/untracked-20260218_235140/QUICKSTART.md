# Quick Start Guide - Hustle XAU Arbitrage System

## Prerequisites

Before starting, ensure you have:
- ✅ Python 3.11+
- ✅ Node.js 18+
- ✅ PostgreSQL 15+ (running)
- ✅ Redis 7+ (running)

## Step-by-Step Setup

### 1. Database Setup

Create the PostgreSQL database:

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE hustle_db;
CREATE USER hustle_user WITH PASSWORD 'hustle_password';
GRANT ALL PRIVILEGES ON DATABASE hustle_db TO hustle_user;
\q
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your configuration

# Run database migrations
alembic upgrade head

# Initialize platform data
python -m app.scripts.init_platforms

# Create test user
python create_test_user.py
```

**Expected Output:**
```
✓ Test user created successfully!
  Username: admin
  Password: admin123
  Email: admin@hustle.com
  User ID: 1
```

### 3. Start Backend

```bash
# From backend directory
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Verify backend is running:**
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### 4. Frontend Setup

```bash
# In a new terminal
cd frontend

# Install dependencies (already done)
npm install

# Start development server
npm run dev
```

**Access frontend:**
- URL: http://localhost:3000

### 5. Login

Use the test credentials:
- **Username:** `admin`
- **Password:** `admin123`

## Quick Test

### Test Backend API

```bash
# Health check
curl http://localhost:8000/health

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123"

# Get market data
curl http://localhost:8000/api/v1/market/data/XAUUSD \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Test Frontend

1. Open http://localhost:3000
2. Login with admin/admin123
3. Navigate to Dashboard
4. Check Trading page
5. View Strategies

## Troubleshooting

### Backend won't start

**Issue:** Database connection error
```bash
# Check PostgreSQL is running
psql -U postgres -c "SELECT version();"

# Check database exists
psql -U postgres -l | grep hustle_db
```

**Issue:** Redis connection error
```bash
# Check Redis is running
redis-cli ping
# Should return: PONG
```

**Issue:** Migration errors
```bash
# Reset migrations
alembic downgrade base
alembic upgrade head
```

### Frontend won't start

**Issue:** Port 3000 already in use
```bash
# Kill process on port 3000
# Windows:
netstat -ano | findstr :3000
taskkill /PID <PID> /F

# Linux/Mac:
lsof -ti:3000 | xargs kill -9
```

**Issue:** API connection error
- Check backend is running on port 8000
- Check CORS settings in backend/.env
- Check Vite proxy in frontend/vite.config.js

### Login fails

**Issue:** Invalid credentials
```bash
# Recreate test user
cd backend
python create_test_user.py
```

**Issue:** 401 Unauthorized
- Check JWT secret in backend/.env
- Clear browser localStorage
- Try incognito/private window

## Environment Configuration

### Backend (.env)

```env
# Database
DATABASE_URL=postgresql://hustle_user:hustle_password@localhost:5432/hustle_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# Environment
ENVIRONMENT=development
```

### Frontend (.env)

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Default Ports

- **Frontend:** 3000
- **Backend:** 8000
- **PostgreSQL:** 5432
- **Redis:** 6379

## Next Steps

After successful setup:

1. **Add Exchange API Keys**
   - Go to Accounts page
   - Add Binance API credentials
   - Add Bybit MT5 credentials

2. **Create Strategy**
   - Go to Strategies page
   - Create forward/reverse arbitrage strategy
   - Set min spread threshold

3. **Start Trading**
   - Go to Trading page
   - Monitor market data
   - Execute manual arbitrage
   - Or start automated strategy

4. **Monitor Risk**
   - Go to Risk page
   - Check account risk ratio
   - Monitor MT5 status
   - Set up alerts

## Production Deployment

For production deployment, see:
- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)
- [Deployment Guide](DEPLOYMENT.md) (to be created)

## Support

For issues or questions:
- Check logs: `backend/logs/` and browser console
- Review API docs: http://localhost:8000/docs
- Check system status: http://localhost:8000/health

## System Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │────▶│  PostgreSQL │
│  (Vue 3)    │     │  (FastAPI)  │     │             │
│  Port 3000  │     │  Port 8000  │     │  Port 5432  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │    Redis    │
                    │  Port 6379  │
                    └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Binance    │
                    │  Bybit MT5  │
                    └─────────────┘
```

## Features Available

### Phase 1-6 (Backend) ✅
- User authentication & management
- Account management (Binance + Bybit MT5)
- Real-time market data streaming
- Forward/Reverse arbitrage execution
- Chase order logic (3-second retry)
- MT5 stuck detection
- Risk monitoring & alerts
- Emergency stop mechanism
- Automated strategy execution
- Position monitoring & auto-close
- Ladder order strategy

### Frontend ✅
- Responsive design (PC, tablet, mobile)
- Dashboard with stats & overview
- Trading interface with order book
- Strategy management
- Position monitoring
- Account management
- Risk control dashboard

## License

Proprietary - All rights reserved
