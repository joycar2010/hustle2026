for ($i = 1; $i -le 8; $i++) {
    $t = Get-Date -Format "HH:mm:ss"
    $f = "D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
    if (Test-Path $f) {
        $age = [int]((Get-Date) - (Get-Item $f).LastWriteTime).TotalSeconds
        $meta = Get-Content $f -Raw | ConvertFrom-Json
        Write-Host "[$t] meta.json age=${age}s connected=$($meta.connected) last_ok=$($meta.last_ok_at)"
        if ($age -lt 30) { Write-Host "  EA is FRESH - done!"; break }
    } else {
        Write-Host "[$t] meta.json not found yet"
    }
    Start-Sleep -Seconds 10
}
