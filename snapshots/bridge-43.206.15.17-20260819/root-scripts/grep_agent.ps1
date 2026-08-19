$out = @()
$lines = Get-Content D:\MT4LAB\agent\main.py
$i = 0
foreach ($line in $lines) {
    $i++
    if ($line -match "connected|healthy|last_ok|TERMINAL_FILES|state/" -and $line -notmatch "^\s*#") {
        $out += "${i}: ${line}"
    }
}
$out | Select-Object -First 40
