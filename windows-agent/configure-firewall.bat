@echo off
echo 正在配置 Windows 防火墙允许内网访问 9000 端口...
echo.

REM 删除旧规则
netsh advfirewall firewall delete rule name="MT5 Windows Agent" >nul 2>&1

REM 添加新规则 - 允许来自内网的 TCP 9000
netsh advfirewall firewall add rule name="MT5 Windows Agent" dir=in action=allow protocol=TCP localport=9000 remoteip=172.31.0.0/16 profile=any

if %errorlevel% equ 0 (
    echo [成功] 防火墙规则已添加
    echo.
    echo 规则详情:
    netsh advfirewall firewall show rule name="MT5 Windows Agent"
) else (
    echo [失败] 防火墙配置失败，请以管理员身份运行
)

echo.
pause
