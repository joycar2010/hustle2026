# 检查所有 MT5 terminal64.exe 进程
Write-Host "=== MT5 Terminal 进程检查 ===" -ForegroundColor Cyan
Write-Host ""

$processes = Get-Process -Name terminal64 -ErrorAction SilentlyContinue

if ($processes) {
    Write-Host "找到 $($processes.Count) 个 MT5 进程:" -ForegroundColor Green
    Write-Host ""

    foreach ($proc in $processes) {
        $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)"

        Write-Host "进程 ID: $($proc.Id)" -ForegroundColor Yellow
        Write-Host "  可执行文件: $($wmi.ExecutablePath)"
        Write-Host "  命令行: $($wmi.CommandLine)"
        Write-Host "  启动时间: $($proc.StartTime)"
        Write-Host "  内存: $([math]::Round($proc.WorkingSet64/1MB, 2)) MB"
        Write-Host ""
    }
} else {
    Write-Host "未找到 terminal64.exe 进程" -ForegroundColor Red
}

Write-Host "=== 预期的 MT5 实例 ===" -ForegroundColor Cyan
Write-Host "端口 8001: C:\Program Files\MetaTrader 5\terminal64.exe"
Write-Host "端口 8002: D:\MetaTrader 5-01\terminal64.exe"
