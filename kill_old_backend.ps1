$targetPids = @(9328, 8464)
foreach ($p in $targetPids) {
    try {
        Stop-Process -Id $p -Force -ErrorAction Stop
        Write-Host "Killed process $p"
    } catch {
        Write-Host "Process $p not found or already dead"
    }
}
Start-Sleep 2
Write-Host "Remaining Python processes:"
Get-Process | Where-Object {$_.Name -like "*python*"} | Select-Object Id, Name, StartTime | Format-Table
Write-Host "Port 8001 listeners:"
netstat -ano | findstr ":8001.*LISTENING"
