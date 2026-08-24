$ErrorActionPreference='SilentlyContinue'
$log="D:\QHMT5\logs\supervisor.log"
$holdDir="D:\QHMT5\holds"
New-Item -ItemType Directory -Force $holdDir | Out-Null
function Log($m){ "$([DateTime]::Now.ToString('MM-dd HH:mm:ss')) $m" | Add-Content $log }
$me=$PID
$others=Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*supervisor.ps1*' -and $_.ProcessId -ne $me }
if($others){ Log "another supervisor(pid $($others.ProcessId)) running; exit self=$me"; exit }
Log "=== supervisor start pid=$me sess=$([System.Diagnostics.Process]::GetCurrentProcess().SessionId) ==="
$insts=@(@{n='by01';port=8001;fam='bybit'},@{n='icsys';port=8888;fam='ic'},@{n='ic01';port=8021;fam='ic'},@{n='bysys';port=8886;fam='bybit'})
function Running($i){ [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*--port $($i.port)*" }) }
function Held($i){ Test-Path "$holdDir\$($i.n).hold" }
function StartB($i){ $dir="D:\QHMT5\instances\$($i.n)"; $py="D:\QHMT5\runtime\releases\v1\venv-$($i.fam)\Scripts\python.exe"; $bridge=Start-Process -FilePath $py -ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port',"$($i.port)" -WorkingDirectory $dir -RedirectStandardError "$dir\logs\bridge.err.log" -RedirectStandardOutput "$dir\logs\bridge.out.log" -WindowStyle Hidden -PassThru; try { $bridge.PriorityClass=[System.Diagnostics.ProcessPriorityClass]::BelowNormal } catch {}; Log "started $($i.n) priority=BelowNormal" }
function KillB($i){ Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*--port $($i.port)*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Where-Object { $_.CommandLine -like "*terminals\$($i.n)\*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } }
function Dedup($i){ $ps=@(Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Where-Object { $_.CommandLine -like "*terminals\$($i.n)\*" }); if($ps.Count -gt 1){ $ps | Select-Object -Skip 1 | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Log "dedup $($i.n) killed $($ps.Count-1) extra terms" } }
foreach($i in $insts){ if(Held $i){ KillB $i; Log "manual hold $($i.n)" } elseif(-not (Running $i)){ StartB $i; Start-Sleep 15 } else { Log "adopt $($i.n) (already running)" } }
Start-Sleep 60
$bad=@{}; $lastR=@{}; $wasHeld=@{}
while($true){
  foreach($i in $insts){
    if(Held $i){
      if(-not $wasHeld[$i.n]){ KillB $i; Log "manual hold $($i.n)" }
      $wasHeld[$i.n]=$true; $bad[$i.n]=0; continue
    }
    if($wasHeld[$i.n]){ Log "manual resume $($i.n)"; StartB $i; Start-Sleep 15; $wasHeld[$i.n]=$false }
    Dedup $i
    $ok=$false
    try{ $h=Invoke-RestMethod "http://127.0.0.1:$($i.port)/health" -TimeoutSec 6; $ok=[bool]$h.mt5 }catch{ $ok=$false }
    if($ok){ if($bad[$i.n]){Log "recovered $($i.n)"}; $bad[$i.n]=0 }
    else{ $bad[$i.n]=[int]$bad[$i.n]+1; Log "unhealthy $($i.n) bad=$($bad[$i.n])"; if($bad[$i.n] -ge 3){ $lr=$lastR[$i.n]; if(-not $lr -or ((Get-Date)-$lr).TotalSeconds -gt 180){ Log "RESTART $($i.n)"; KillB $i; Start-Sleep 5; StartB $i; $lastR[$i.n]=Get-Date; $bad[$i.n]=0 } } }
  }
  Start-Sleep 30
}


