@echo off
REM 使用 NSSM 安装 Windows Agent 为系统服务

echo ========================================
echo 安装 MT5 Windows Agent 服务
echo ========================================

REM 检查 NSSM 是否存在
if not exist "C:\nssm\nssm.exe" (
    echo 错误: 未找到 NSSM，请先安装 NSSM
    echo 下载地址: https://nssm.cc/download
    pause
    exit /b 1
)

REM 停止并删除旧服务（如果存在）
C:\nssm\nssm.exe stop MT5Agent
C:\nssm\nssm.exe remove MT5Agent confirm

REM 安装新服务
C:\nssm\nssm.exe install MT5Agent python C:\MT5Agent\main.py
C:\nssm\nssm.exe set MT5Agent AppDirectory C:\MT5Agent
C:\nssm\nssm.exe set MT5Agent DisplayName "MT5 Windows Agent"
C:\nssm\nssm.exe set MT5Agent Description "MT5实例管理服务"
C:\nssm\nssm.exe set MT5Agent Start SERVICE_AUTO_START

REM 启动服务
C:\nssm\nssm.exe start MT5Agent

echo.
echo ========================================
echo 服务安装完成！
echo 服务名称: MT5Agent
echo 端口: 9000
echo ========================================
pause
