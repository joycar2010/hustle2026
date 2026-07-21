$out = "D:\QHMT5\logs\seed_login.log"
"=== seed $(Get-Date) sess=$([System.Diagnostics.Process]::GetCurrentProcess().SessionId) ===" | Set-Content $out
Get-Process terminal64,python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 3
foreach ($n in 'icsysnew','icsys','ic01','bysys') {
  $dir="D:\QHMT5\instances\$n"; $h=@{}
  Get-Content "$dir\.env" | ForEach-Object { if ($_ -match '^(\w+)=(.*)$'){ $h[$matches[1]]=$matches[2].Trim("'") } }
  $fam= if ($n -eq 'bysys'){'bybit'}else{'ic'}
  $py="D:\QHMT5\runtime\releases\v1\venv-$fam\Scripts\python.exe"
  $code = "import MetaTrader5 as m" + [char]10 + "ok=m.initialize(path=r'''" + $h['MT5_PATH'] + "''', login=" + $h['MT5_LOGIN'] + ", password=r'''" + $h['MT5_PASSWORD'] + "''', server='" + $h['MT5_SERVER'] + "', timeout=120000)" + [char]10 + "ai=m.account_info()" + [char]10 + "print('OK',ok,'ERR',m.last_error(),'ACC',(ai.login if ai else None),(ai.server if ai else None),(ai.company if ai else None))" + [char]10 + "m.shutdown()"
  $cf = "$dir\seed_tmp.py"; [System.IO.File]::WriteAllText($cf,$code)
  $r = & $py $cf 2>&1
  "[$n] $r" | Add-Content $out
  Start-Sleep 6
}
"accounts.dat status:" | Add-Content $out
foreach ($n in 'icsysnew','icsys','ic01','bysys') { ("  $n=" + (Test-Path "D:\QHMT5\terminals\$n\config\accounts.dat")) | Add-Content $out }
"done $(Get-Date)" | Add-Content $out