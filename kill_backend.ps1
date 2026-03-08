# Kill all backend processes
Write-Host "Stopping all backend processes..."

# Method 1: Kill by port
$connections = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
    $processId = $conn.OwningProcess
    Write-Host "Killing process $processId on port 8000"
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

# Method 2: Kill Python processes running uvicorn
$processes = Get-Process python -ErrorAction SilentlyContinue
foreach ($proc in $processes) {
    $cmdLine = (Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)").CommandLine
    if ($cmdLine -like "*uvicorn*" -or $cmdLine -like "*app.main*") {
        Write-Host "Killing Python process $($proc.Id): $cmdLine"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "All backend processes stopped"
