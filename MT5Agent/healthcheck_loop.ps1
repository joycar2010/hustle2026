# Wrapper that runs healthcheck.ps1 twice at T and T+30s per invocation.
# Scheduler triggers this every 1 minute.
& 'C:\MT5Agent\healthcheck.ps1'
Start-Sleep -Seconds 30
& 'C:\MT5Agent\healthcheck.ps1'
