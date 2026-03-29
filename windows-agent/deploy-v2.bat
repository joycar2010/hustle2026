@echo off
REM Windows Agent V2 自动部署脚本
REM 需要以管理员身份运行

echo ========================================
echo Windows Agent V2 部署
echo ========================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    pause
    exit /b 1
)

echo [1/5] 停止当前 Agent...
powershell -Command "Get-Process -Name python | Where-Object {$_.CommandLine -like '*MT5Agent*' -or $_.CommandLine -like '*main.py*'} | Stop-Process -Force"
timeout /t 2 >nul

echo [2/5] 备份当前版本...
cd C:\MT5Agent
if exist main.py (
    copy /Y main.py main.py.backup
    echo 已备份到 main.py.backup
)

echo [3/5] 检查新版本文件...
if not exist main_v2.py (
    echo [错误] 找不到 main_v2.py 文件！
    echo 请将 main_v2.py 放到 C:\MT5Agent\ 目录
    pause
    exit /b 1
)

echo [4/5] 部署新版本...
copy /Y main_v2.py main.py
echo 新版本已部署

echo [5/5] 启动 Agent...
start /B python main.py
timeout /t 3 >nul

echo.
echo [验证] 测试 Agent 状态...
curl http://localhost:9000/ 2>nul
if %errorLevel% equ 0 (
    echo.
    echo [成功] Agent V2 部署完成！
) else (
    echo.
    echo [警告] Agent 可能未正常启动，请检查
)

echo.
echo ========================================
echo 部署完成
echo ========================================
echo.
echo 版本信息：
echo - 旧版本备份：C:\MT5Agent\main.py.backup
echo - 当前版本：V2.0.0
echo.
echo 测试命令：
echo   curl http://localhost:9000/
echo   curl http://localhost:9000/instances
echo.
pause
