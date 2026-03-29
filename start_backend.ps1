# Kill process on port 8000 if exists
$conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

# Start backend service
Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d C:\app\hustle2026\backend && C:\Python39\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> backend_live.log 2>&1" -WindowStyle Hidden
