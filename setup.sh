#!/bin/bash
# Hustle XAU System - Quick Setup Script

echo "=== Hustle XAU Arbitrage System Setup ==="
echo ""

# Step 1: Check if PostgreSQL and Redis are running
echo "Step 1: Checking services..."
echo "Please ensure PostgreSQL and Redis are running on your system"
echo ""

# Step 2: Set up backend
echo "Step 2: Setting up backend..."
cd backend

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cat > .env << EOF
# Database
DATABASE_URL=postgresql://hustle_user:hustle_password@localhost:5432/hustle_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=$(openssl rand -hex 32)
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# API
BINANCE_API_BASE=https://fapi.binance.com
BYBIT_API_BASE=https://api.bybit.com

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# Environment
ENVIRONMENT=development
EOF
    echo "✓ .env file created"
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Initialize platform data
echo "Initializing platform data..."
python -m app.scripts.init_platforms

echo ""
echo "=== Backend Setup Complete ==="
echo ""
echo "To start the backend:"
echo "  cd backend"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo "To create a test user, run:"
echo "  python create_test_user.py"
