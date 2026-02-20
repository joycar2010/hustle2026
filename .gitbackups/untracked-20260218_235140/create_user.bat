@echo off
echo ========================================
echo Hustle XAU - Create Test User
echo ========================================
echo.

cd backend

echo Creating test user...
python create_test_user.py

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Test User Credentials:
echo   Username: admin
echo   Password: admin123
echo   Email: admin@hustle.com
echo.
echo Next Steps:
echo   1. Start backend: cd backend ^&^& uvicorn app.main:app --reload
echo   2. Start frontend: cd frontend ^&^& npm run dev
echo   3. Open browser: http://localhost:3000
echo   4. Login with admin/admin123
echo.
pause
