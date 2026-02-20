# Hustle XAU Arbitrage System - Backend

FastAPI-based backend for cross-platform XAU arbitrage between Binance XAUUSDT and Bybit MT5 XAUUSD.s.

## Features

- User authentication with JWT
- Multi-account management (Binance + Bybit MT5)
- Strategy configuration
- Real-time market data integration
- Risk monitoring and alerts
- WebSocket support for live updates

## Tech Stack

- **Framework**: FastAPI 0.109.0
- **Database**: PostgreSQL with SQLAlchemy 2.0
- **Cache**: Redis
- **Authentication**: JWT (python-jose)
- **Password Hashing**: bcrypt (passlib)
- **Migrations**: Alembic

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and update values:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:
- Database URL
- Redis URL
- JWT secret key
- API endpoints

### 3. Set Up Database

Make sure PostgreSQL is running, then create the database:

```bash
createdb hustle_db
```

Run migrations:

```bash
alembic upgrade head
```

### 4. Initialize Platform Data

Run the initialization script to populate platform data:

```bash
python -m app.scripts.init_platforms
```

### 5. Run the Application

Development mode:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Production mode:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Documentation

Once the server is running, access:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - User login

### Users
- `GET /api/v1/users/me` - Get current user
- `PUT /api/v1/users/me` - Update current user

### Accounts
- `GET /api/v1/accounts` - List accounts
- `POST /api/v1/accounts` - Create account
- `GET /api/v1/accounts/{id}` - Get account
- `PUT /api/v1/accounts/{id}` - Update account
- `DELETE /api/v1/accounts/{id}` - Delete account

### Strategies
- `GET /api/v1/strategies/configs` - List strategy configs
- `POST /api/v1/strategies/configs` - Create strategy config
- `GET /api/v1/strategies/configs/{id}` - Get strategy config
- `PUT /api/v1/strategies/configs/{id}` - Update strategy config
- `DELETE /api/v1/strategies/configs/{id}` - Delete strategy config

## Database Migrations

Create a new migration:

```bash
alembic revision --autogenerate -m "description"
```

Apply migrations:

```bash
alembic upgrade head
```

Rollback migration:

```bash
alembic downgrade -1
```

## Testing

Run tests:

```bash
pytest
```

With coverage:

```bash
pytest --cov=app --cov-report=html
```

## Project Structure

```
backend/
├── app/
│   ├── api/v1/          # API endpoints
│   ├── core/            # Core configuration
│   ├── models/          # Database models
│   ├── schemas/         # Pydantic schemas
│   ├── services/        # Business logic
│   ├── websocket/       # WebSocket handlers
│   └── tasks/           # Background tasks
├── alembic/             # Database migrations
├── tests/               # Test files
├── requirements.txt     # Dependencies
└── .env.example         # Environment template
```

## Development

### Code Style

Format code with Black:

```bash
black app/
```

Lint with flake8:

```bash
flake8 app/
```

Type check with mypy:

```bash
mypy app/
```

## License

Proprietary - All rights reserved

## Support

For issues and questions, contact the development team.
