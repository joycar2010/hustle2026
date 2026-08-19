$ErrorActionPreference = 'Stop'
$api = (Get-Content -LiteralPath 'D:\QHCELL\cell.env' |
    Where-Object { $_ -match '^API_KEY=' } | Select-Object -First 1).Substring(8).Trim().Trim('"').Trim("'")
$env:API_KEY = $api
$env:INSTANCE_NAME = 'qhcell-m4'
$env:TERMINAL_FILES_DIR = 'D:\QHCELL\pool\m4\terminal\MQL4\Files\qhbridge'
$env:SERVICE_PORT = '8068'
$env:CMD_WAIT_SEC = '20'
$env:SYNC_WAIT_SEC = '0.85'
$proc = Start-Process -FilePath 'D:\MT4LAB\agent\venv\Scripts\python.exe' `
    -ArgumentList @('-m','uvicorn','main:app','--host','0.0.0.0','--port','8068') `
    -WorkingDirectory 'D:\MT4LAB\agent' -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput 'D:\MT4LAB\agent\logs\recovery3-m4.out.log' `
    -RedirectStandardError 'D:\MT4LAB\agent\logs\recovery3-m4.err.log'
Start-Sleep -Seconds 5
if ($proc.HasExited) { throw "m4 process exited with code $($proc.ExitCode)" }
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8068/health' -Headers @{'X-API-Key'=$api} -TimeoutSec 5
if (-not $health.mt5 -or $health.trade_allowed -eq $false) { throw 'm4 health is not trade-ready' }
[ordered]@{pid=$proc.Id;mt5=$health.mt5;trade_allowed=$health.trade_allowed} | ConvertTo-Json -Compress
