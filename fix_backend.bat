@echo off
chcp 65001 >nul
title Hustle2026 Backend Fix Tool
color 0E

echo.
echo ========================================
echo   Hustle2026 后端修复工具
echo ========================================
echo.
echo 检测到问题: 后端进程存在但无法响应请求
echo 原因: Windows CLOSE_WAIT 连接堆积导致端口占用
echo.

REM Step 1: 检查当前状态
echo [1/4] 检查当前后端状态...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %ERRORLEVEL%==0 (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
        echo     发现后端进程 PID: %%a
        set BACKEND_PID=%%a
    )
) else (
    echo     后端未运行
)

REM Step 2: 统计 CLOSE_WAIT 连接数
echo [2/4] 统计 CLOSE_WAIT 连接数...
for /f %%c in ('netstat -ano ^| findstr ":8000" ^| findstr "CLOSE_WAIT" ^| find /c "CLOSE_WAIT"') do (
    echo     CLOSE_WAIT 连接数: %%c
)

REM Step 3: 强制终止旧进程
echo [3/4] 终止旧后端进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo     终止 PID %%a ...
    taskkill /PID %%a /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq Hustle2026-Backend" /F >nul 2>&1
REM 等待连接释放
timeout /t 3 /nobreak >nul

REM Step 4: 重新启动后端
echo [4/4] 重新启动后端服务...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if "%ERRORLEVEL%"=="0" (
    echo     警告: 端口 8000 仍被占用，请手动检查
    goto :check
)

start "Hustle2026-Backend" /D "C:\app\hustle2026\backend" cmd /k "C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> backend_live.log 2>&1"
echo     后端已启动，等待初始化...
timeout /t 8 /nobreak >nul

:check
echo.
echo ========================================
echo   验证修复结果
echo ========================================
curl -s --max-time 5 http://172.31.5.62:8000/api/v1/market/orderbook >nul 2>&1
if %ERRORLEVEL%==0 (
    color 0A
    echo   ✓ 后端 API 响应正常，修复成功！
) else (
    color 0C
    echo   ✗ 后端仍无响应，请查看 backend_live.log
    echo   日志路径: C:\app\hustle2026\backend\backend_live.log
)

echo.
echo 按任意键关闭...
pause >nul
