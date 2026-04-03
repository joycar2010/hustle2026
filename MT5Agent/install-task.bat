@echo off
REM 使用 Windows 任务计划程序配置开机自启

echo ========================================
echo 配置 MT5 Windows Agent 开机自启
echo ========================================

REM 删除旧任务（如果存在）
schtasks /Delete /TN "MT5Agent" /F 2>nul

REM 创建新任务
schtasks /Create /TN "MT5Agent" /TR "python C:\MT5Agent\main.py" /SC ONSTART /RU SYSTEM /RL HIGHEST /F

echo.
echo ========================================
echo 配置完成！
echo 任务名称: MT5Agent
echo 触发器: 系统启动时
echo 运行账户: SYSTEM
echo ========================================
echo.
echo 手动启动任务: schtasks /Run /TN "MT5Agent"
echo 查看任务状态: schtasks /Query /TN "MT5Agent"
echo ========================================
pause
