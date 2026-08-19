# QHBridge MT4 Lab launcher - PORTABLE cutover variant (Step 2 "unify all to portable").
# Launches the portable terminals under D:\MT4LAB\terminals with /portable so data/EA live next to exe.
# Must run in the interactive session (MT4LAB-Startup task, LogonType Interactive) so the GUI/login renders.
# Idempotent: skips a terminal already running from its portable path.
$terminals = @(
  @{ name = 'ic';     exe = 'D:\MT4LAB\terminals\ic\terminal.exe' }
  @{ name = 'exness'; exe = 'D:\MT4LAB\terminals\exness\terminal.exe' }
)
foreach ($t in $terminals) {
  $run = Get-Process terminal -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $t.exe }
  if (-not $run) {
    Start-Process $t.exe -ArgumentList '/portable' -WorkingDirectory (Split-Path $t.exe -Parent)
    Start-Sleep 10
  }
}
