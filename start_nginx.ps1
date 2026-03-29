# Kill existing nginx processes
Get-Process nginx -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Start nginx
Start-Process -FilePath "C:\nginx\nginx.exe" -WorkingDirectory "C:\nginx" -WindowStyle Hidden
