$src = Get-Content D:\QHCELL\cell.py -Raw

# VENV_PY定义
$src -split "`n" | Select-String -Pattern "VENV_PY|venv_py" | Select-Object -First 15

Write-Host "---POPEN---"
$lines = $src -split "`n"
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "Popen") {
        Write-Host "$($i+1): $($lines[$i])"
        Write-Host "$($i+2): $($lines[$i+1])"
        Write-Host "$($i+3): $($lines[$i+2])"
        Write-Host ""
    }
}

Write-Host "---FAMILY/VENV---"
$src -split "`n" | Select-String -Pattern "family|FAMILY|venv|templates" | Select-Object -First 20
