Write-Host "=== filebridge.py is_fresh threshold ==="
$lines = Get-Content D:\MT4LAB\agent\filebridge.py
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "is_fresh|freshness|max_age|MAX_AGE|age") {
        Write-Host "$($i+1): $($lines[$i])"
    }
}

Write-Host "`n=== agent main.py connection check age param ==="
$ml = Get-Content D:\MT4LAB\agent\main.py
for ($i = 0; $i -lt $ml.Count; $i++) {
    if ($ml[$i] -match "is_fresh|age\s*=|MAX_AGE|META_AGE") {
        Write-Host "$($i+1): $($ml[$i])"
    }
}
