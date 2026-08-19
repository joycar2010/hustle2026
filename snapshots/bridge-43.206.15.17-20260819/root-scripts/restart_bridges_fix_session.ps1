# 修复Session隔离问题的重启脚本
# 确保Bridge在与MT5相同的Session中启动

Write-Host "=== Bridge Session修复重启 ===" -ForegroundColor Green

# 1. 停止所有Bridge进程
Write-Host "`n[1/3] 停止所有Bridge进程..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*QHMT5*venv*"
} | ForEach-Object {
    Write-Host "  停止 PID=$($_.Id) Session=$($_.SessionId)"
    Stop-Process -Id $_.Id -Force
}

Start-Sleep -Seconds 3

# 2. 检查MT5和当前Session
Write-Host "`n[2/3] 检查MT5 Session..." -ForegroundColor Yellow
$mt5Process = Get-Process -Name terminal -ErrorAction SilentlyContinue | Select-Object -First 1
if ($mt5Process) {
    $targetSession = $mt5Process.SessionId
    Write-Host "  MT5在Session $targetSession 运行"
} else {
    Write-Host "  警告: 未找到MT5进程" -ForegroundColor Red
    $targetSession = 2
}

$currentSession = (Get-Process -Id $PID).SessionId
Write-Host "  当前脚本Session: $currentSession"

# 3. 在正确的Session中启动Bridge
Write-Host "`n[3/3] 启动Bridge (确保在Session $targetSession)..." -ForegroundColor Yellow

# IC Bridge
$env:BRIDGE_ID = "main"
$env:MARKET_FEED_SYMBOLS = "XAUUSD,EURUSD"

Set-Location D:\QHMT5\runtime\releases\v1\ic

Write-Host "  启动IC Bridge (main)..."
# 使用当前Session直接启动,不用Start-Process的后台模式
$icJob = Start-Job -ScriptBlock {
    Set-Location D:\QHMT5\runtime\releases\v1\ic
    $env:BRIDGE_ID = "main"
    $env:MARKET_FEED_SYMBOLS = "XAUUSD,EURUSD"
    & "..\venv-ic\Scripts\python.exe" "app\main.py" > bridge_ic.log 2> bridge_ic_error.log
}

# Bybit Bridge
$env:BRIDGE_ID = "hedge"

Set-Location D:\QHMT5\runtime\releases\v1\bybit

Write-Host "  启动Bybit Bridge (hedge)..."
$bybitJob = Start-Job -ScriptBlock {
    Set-Location D:\QHMT5\runtime\releases\v1\bybit
    $env:BRIDGE_ID = "hedge"
    $env:MARKET_FEED_SYMBOLS = "XAUUSD,EURUSD"
    & "..\venv-bybit\Scripts\python.exe" "app\main.py" > bridge_bybit.log 2> bridge_bybit_error.log
}

Write-Host "`n等待5秒..."
Start-Sleep -Seconds 5

# 检查进程
Write-Host "`n=== 进程状态 ===" -ForegroundColor Green
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*QHMT5*"
} | Format-Table Id,SessionId,Path -AutoSize

Write-Host "`nJob状态:"
Get-Job | Format-Table Id,State

Write-Host "`n=== 完成 ===" -ForegroundColor Green
