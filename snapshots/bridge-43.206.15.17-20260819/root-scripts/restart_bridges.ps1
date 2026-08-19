# P1.3 Bridge端重启脚本

Write-Host "=== P1.3 Bridge端服务重启 ===" -ForegroundColor Green

# 1. 停止现有Bridge进程
Write-Host "`n[1/3] 停止现有Bridge进程..." -ForegroundColor Yellow

Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*QHMT5*"
} | ForEach-Object {
    Write-Host "  停止进程 PID=$($_.Id) Path=$($_.Path)"
    Stop-Process -Id $_.Id -Force
}

Start-Sleep -Seconds 3

# 2. 设置环境变量并启动IC Bridge (主腿)
Write-Host "`n[2/3] 启动IC Bridge (主腿)..." -ForegroundColor Yellow

$env:BRIDGE_ID = "main"
$env:MARKET_FEED_SYMBOLS = "XAUUSD,EURUSD"

Set-Location D:\QHMT5\runtime\releases\v1\ic

Write-Host "  环境变量:"
Write-Host "    BRIDGE_ID=$env:BRIDGE_ID"
Write-Host "    MARKET_FEED_SYMBOLS=$env:MARKET_FEED_SYMBOLS"

# 启动IC Bridge (后台)
Start-Process -FilePath "..\venv-ic\Scripts\python.exe" -ArgumentList "app\main.py" -NoNewWindow -RedirectStandardOutput "bridge_ic.log" -RedirectStandardError "bridge_ic_error.log"

Write-Host "  IC Bridge已启动"

# 3. 设置环境变量并启动Bybit Bridge (对冲腿)
Write-Host "`n[3/3] 启动Bybit Bridge (对冲腿)..." -ForegroundColor Yellow

$env:BRIDGE_ID = "hedge"
$env:MARKET_FEED_SYMBOLS = "XAUUSD,EURUSD"

Set-Location D:\QHMT5\runtime\releases\v1\bybit

Write-Host "  环境变量:"
Write-Host "    BRIDGE_ID=$env:BRIDGE_ID"
Write-Host "    MARKET_FEED_SYMBOLS=$env:MARKET_FEED_SYMBOLS"

# 启动Bybit Bridge (后台)
Start-Process -FilePath "..\venv-bybit\Scripts\python.exe" -ArgumentList "app\main.py" -NoNewWindow -RedirectStandardOutput "bridge_bybit.log" -RedirectStandardError "bridge_bybit_error.log"

Write-Host "  Bybit Bridge已启动"

# 4. 等待服务启动
Write-Host "`n等待服务启动..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

# 5. 检查进程
Write-Host "`n=== 服务状态检查 ===" -ForegroundColor Green

Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*QHMT5*"
} | Format-Table Id, @{Label="Path";Expression={$_.Path}} -AutoSize

Write-Host "`n=== 部署完成! ===" -ForegroundColor Green
Write-Host "请在QH服务器验证:" -ForegroundColor Cyan
Write-Host "  ssh ubuntu@54.238.164.60" -ForegroundColor White
Write-Host "  redis-cli -n 3 KEYS 'bridge:*:tick:*'" -ForegroundColor White
Write-Host "  redis-cli -n 3 HGETALL 'bridge:main:tick:XAUUSD'" -ForegroundColor White
Write-Host "  curl http://127.0.0.1:8090/api/admin/tick_cache_stats" -ForegroundColor White
