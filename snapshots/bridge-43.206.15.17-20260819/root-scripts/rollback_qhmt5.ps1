Write-Host "=== Rollback D:\QHMT5 MT5 bridges ==="

Copy-Item D:\QHMT5\runtime\releases\v1\ic\app\main.py.backup_20260723_191448 D:\QHMT5\runtime\releases\v1\ic\app\main.py -Force
Write-Host "ic main.py restored"

Copy-Item D:\QHMT5\runtime\releases\v1\bybit\app\main.py.backup_20260723_191815 D:\QHMT5\runtime\releases\v1\bybit\app\main.py -Force
Write-Host "bybit main.py restored"

Remove-Item D:\QHMT5\runtime\releases\v1\ic\app\market_feed_agent.py -Force -ErrorAction SilentlyContinue
Remove-Item D:\QHMT5\runtime\releases\v1\bybit\app\market_feed_agent.py -Force -ErrorAction SilentlyContinue
Write-Host "market_feed_agent.py removed"

# Kill stray processes started by my restart script (wrong ports/env)
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*QHMT5*" } | ForEach-Object {
    Write-Host "Killing stray PID=$($_.Id)"
    Stop-Process -Id $_.Id -Force
}

# Also kill orphan PowerShell jobs from my session-fix attempt
Get-Job -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue

Write-Host "=== ROLLBACK DONE - supervisor will re-pull with original code ==="
