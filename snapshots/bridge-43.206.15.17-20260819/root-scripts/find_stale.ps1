$lines = Get-Content D:\MT4LAB\agent\filebridge.py | Select-Object -First 55
foreach ($l in $lines) {
    if ($l -match "STALE|stale|STATE_") { Write-Host $l }
}
