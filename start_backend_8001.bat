@echo off
echo ========================================
echo Starting Hustle XAU Backend Server (Port 8001)
echo ========================================
echo.

cd backend

echo Checking prerequisites...
python -c "import fastapi; import uvicorn; print('✓ Dependencies OK')" 2>nul
if errorlevel 1 (
    echo ✗ Dependencies missing. Installing...
    pip install -r requirements.txt
)

echo.
echo Starting server on http://localhost:8001
echo API Docs: http://localhost:8001/docs
echo.
echo Note: Using port 8001 due to port 8000 conflict
echo.
echo Press Ctrl+C to stop the server
echo.

uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
