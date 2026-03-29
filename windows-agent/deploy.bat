@echo off
REM Windows Agent 部署脚本

echo ========================================
echo MT5 Windows Agent 部署
echo ========================================

REM 创建目录
if not exist "C:\MT5Agent" mkdir "C:\MT5Agent"

REM 复制文件
copy main.py C:\MT5Agent\
copy requirements.txt C:\MT5Agent\

REM 安装依赖
cd C:\MT5Agent
python -m pip install -r requirements.txt

echo.
echo ========================================
echo 部署完成！
echo.
echo 启动服务: python C:\MT5Agent\main.py
echo 或使用 NSSM 安装为 Windows 服务
echo ========================================
pause
