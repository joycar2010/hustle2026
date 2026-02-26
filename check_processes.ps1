Write-Host "All Python processes:"
Get-Process | Where-Object {$_.Name -like "*python*" -or $_.Name -like "*uvicorn*"} | Select-Object Id, Name, CPU, StartTime | Format-Table

Write-Host "Processes on port 8001:"
$connections = netstat -ano | findstr ":8001.*LISTENING"
Write-Host $connections
