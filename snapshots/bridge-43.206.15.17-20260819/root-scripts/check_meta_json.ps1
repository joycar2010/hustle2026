$key = "<REDACTED_API_KEY>"

Write-Host "=== IC meta.json ==="
$f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
if (Test-Path $f) {
    $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
    Write-Host "age=${age}s  size=$((Get-Item $f).Length)bytes"
    Get-Content $f -Raw
} else { "NOT FOUND: $f" }

Write-Host "`n=== Exness meta.json ==="
$f2 = "D:\MT4LAB\terminals\exness\MQL4\Files\qhbridge\state\meta.json"
if (Test-Path $f2) {
    $age2 = [int]((Get-Date) - (Get-Item $f2).LastWriteTime).TotalSeconds
    Write-Host "age=${age2}s  size=$((Get-Item $f2).Length)bytes"
    Get-Content $f2 -Raw
} else { "NOT FOUND: $f2" }

Write-Host "`n=== TERMINAL_FILES_DIR of running 8041 agent ==="
$p41 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($p41) {
    $proc = Get-WmiObject Win32_Process -Filter "ProcessId=$p41"
    Write-Host "PID=$p41 cmdline=$($proc.CommandLine)"
    Write-Host "CWD: $((Get-Process -Id $p41).MainModule.FileName)"
}
