# Clean ports 8000 and 3000
Write-Host "Cleaning ports 8000 and 3000..." -ForegroundColor Yellow

# Get all processes listening on port 8000
$port8000 = netstat -ano | findstr ":8000.*LISTENING"
if ($port8000) {
    $pids8000 = $port8000 | ForEach-Object {
        if ($_ -match '\s+(\d+)\s*$') {
            $matches[1]
        }
    } | Select-Object -Unique

    foreach ($processId in $pids8000) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Killed process $processId (port 8000)" -ForegroundColor Green
        } catch {
            Write-Host "Cannot kill process $processId" -ForegroundColor Red
        }
    }
}

# Get all processes listening on port 3000
$port3000 = netstat -ano | findstr ":3000.*LISTENING"
if ($port3000) {
    $pids3000 = $port3000 | ForEach-Object {
        if ($_ -match '\s+(\d+)\s*$') {
            $matches[1]
        }
    } | Select-Object -Unique

    foreach ($processId in $pids3000) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Killed process $processId (port 3000)" -ForegroundColor Green
        } catch {
            Write-Host "Cannot kill process $processId" -ForegroundColor Red
        }
    }
}

Write-Host "`nWaiting for ports to be released..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Verify ports are released
Write-Host "`nChecking port status..." -ForegroundColor Yellow
$check8000 = netstat -ano | findstr ":8000.*LISTENING"
$check3000 = netstat -ano | findstr ":3000.*LISTENING"

if ($check8000) {
    Write-Host "Warning: Port 8000 still in use" -ForegroundColor Red
    netstat -ano | findstr ":8000.*LISTENING"
} else {
    Write-Host "Port 8000 is free" -ForegroundColor Green
}

if ($check3000) {
    Write-Host "Warning: Port 3000 still in use" -ForegroundColor Red
    netstat -ano | findstr ":3000.*LISTENING"
} else {
    Write-Host "Port 3000 is free" -ForegroundColor Green
}

Write-Host "`nPort cleanup complete!" -ForegroundColor Cyan
