# Stop Windows Agent
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $wmi = Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)"
    if ($wmi.CommandLine -like "*MT5Agent*") {
        Stop-Process -Id $_.Id -Force
        Write-Host "Stopped process $($_.Id)"
    }
}

# Copy new file
Copy-Item C:\Temp\main.py C:\MT5Agent\main.py -Force
Write-Host "File updated"

# Start Windows Agent
Start-Process -FilePath python -ArgumentList "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent" -WindowStyle Hidden
Write-Host "Windows Agent started"
