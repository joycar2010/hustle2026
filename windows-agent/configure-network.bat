@echo off
REM 快速配置 Windows Agent 内网访问
REM 需要以管理员身份运行

echo ========================================
echo Windows Agent 内网访问配置
echo ========================================
echo.

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    pause
    exit /b 1
)

echo [1/3] 配置防火墙规则...
powershell -Command "Remove-NetFirewallRule -DisplayName 'MT5 Windows Agent' -ErrorAction SilentlyContinue"
powershell -Command "New-NetFirewallRule -DisplayName 'MT5 Windows Agent' -Direction Inbound -Protocol TCP -LocalPort 9000 -Action Allow -Profile Any -Description '允许内网访问 MT5 Agent API'"

if %errorLevel% equ 0 (
    echo [成功] 防火墙规则已添加
) else (
    echo [失败] 防火墙配置失败
    pause
    exit /b 1
)

echo.
echo [2/3] 检查 Agent 服务状态...
powershell -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like '*main.py*'} | Select-Object Id, ProcessName"

echo.
echo [3/3] 测试本地连接...
curl http://localhost:9000/ 2>nul
if %errorLevel% equ 0 (
    echo [成功] Agent 服务运行正常
) else (
    echo [警告] Agent 服务可能未运行，请检查
)

echo.
echo ========================================
echo 配置完成！
echo ========================================
echo.
echo 下一步：
echo 1. 在 AWS 控制台配置安全组，允许 172.31.2.22 访问 9000 端口
echo 2. 从 GO 服务器测试: curl http://172.31.14.113:9000/
echo.
pause
