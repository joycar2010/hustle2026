$ErrorActionPreference='SilentlyContinue'
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*cell:app*' }
if ($running) { exit }
$cell = Start-Process -FilePath "D:\QHMT5\runtime\releases\v1\venv-ic\Scripts\python.exe" -ArgumentList '-m','uvicorn','cell:app','--host','0.0.0.0','--port','8600' -WorkingDirectory 'D:\QHCELL' -RedirectStandardOutput 'D:\QHCELL\logs\cell.out.log' -RedirectStandardError 'D:\QHCELL\logs\cell.err.log' -WindowStyle Hidden -PassThru
try { $cell.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::Normal } catch {}
