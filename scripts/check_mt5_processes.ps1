# 检查 Windows 服务器上的 MT5 进程
Write-Host "=== 检查 MT5 Terminal 进程 ===" -ForegroundColor Cyan
Write-Host ""

# 查找所有 terminal64.exe 进程
$mt5Processes = Get-Process -Name terminal64 -ErrorAction SilentlyContinue

if ($mt5Processes) {
    Write-Host "找到 $($mt5Processes.Count) 个 MT5 进程:" -ForegroundColor Green
    Write-Host ""

    foreach ($proc in $mt5Processes) {
        Write-Host "进程 ID: $($proc.Id)" -ForegroundColor Yellow
        Write-Host "  启动时间: $($proc.StartTime)"
        Write-Host "  内存使用: $([math]::Round($proc.WorkingSet64/1MB, 2)) MB"

        # 获取进程的完整路径和命令行
        try {
            $wmiProc = Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)"
            Write-Host "  可执行文件: $($wmiProc.ExecutablePath)"
            Write-Host "  命令行: $($wmiProc.CommandLine)"
            Write-Host "  工作目录: $(Split-Path $wmiProc.ExecutablePath)"
        } catch {
            Write-Host "  无法获取详细信息: $_" -ForegroundColor Red
        }
        Write-Host ""
    }
} else {
    Write-Host "未找到 terminal64.exe 进程" -ForegroundColor Red
    Write-Host ""
}

# 检查桥接服务进程
Write-Host "=== 检查 MT5 桥接服务进程 ===" -ForegroundColor Cyan
Write-Host ""

$bridgeProcesses = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
    $cmdLine -like "*mt5*" -or $cmdLine -like "*8001*" -or $cmdLine -like "*8002*"
}

if ($bridgeProcesses) {
    Write-Host "找到 $($bridgeProcesses.Count) 个桥接服务进程:" -ForegroundColor Green
    Write-Host ""

    foreach ($proc in $bridgeProcesses) {
        $wmiProc = Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)"
        Write-Host "进程 ID: $($proc.Id)" -ForegroundColor Yellow
        Write-Host "  启动时间: $($proc.StartTime)"
        Write-Host "  命令行: $($wmiProc.CommandLine)"
        Write-Host ""
    }
} else {
    Write-Host "未找到桥接服务进程" -ForegroundColor Red
}

# 检查端口占用
Write-Host "=== 检查端口占用 ===" -ForegroundColor Cyan
Write-Host ""

foreach ($port in @(8001, 8002, 9000)) {
    $connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($connection) {
        $proc = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "端口 $port : 被进程 $($proc.Name) (PID: $($proc.Id)) 占用" -ForegroundColor Green
    } else {
        Write-Host "端口 $port : 未被占用" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== 检查完成 ===" -ForegroundColor Cyan
