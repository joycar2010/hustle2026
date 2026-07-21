$log="D:\QHMT5\logs\launch_diag.log"
"=== launch $(Get-Date) sess=$([System.Diagnostics.Process]::GetCurrentProcess().SessionId) ===" | Set-Content $log
Get-Process terminal64,python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 3
foreach ($n in 'icsysnew','icsys','ic01','bysys') {
  $dir="D:\QHMT5\instances\$n"; $fam= if ($n -match 'bysys|by01'){'bybit'}else{'ic'}
  $py="D:\QHMT5\runtime\releases\v1\venv-$fam\Scripts\python.exe"
  $port=(Get-Content "$dir\.env" | Where-Object {$_ -match '^SERVICE_PORT='}) -replace '^SERVICE_PORT=',''
  Start-Process -FilePath $py -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port',$port -WorkingDirectory $dir -RedirectStandardError "$dir\logs\bridge.err.log" -RedirectStandardOutput "$dir\logs\bridge.out.log" -WindowStyle Hidden
  "started bridge $n port $port" | Add-Content $log
  Start-Sleep 15
}
"done $(Get-Date)" | Add-Content $log