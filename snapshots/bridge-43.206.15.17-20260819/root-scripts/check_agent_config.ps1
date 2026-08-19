Write-Host "=== MT4LAB-Agent-ic task action ==="
$t = Get-ScheduledTask -TaskName "MT4LAB-Agent-ic" -ErrorAction SilentlyContinue
$t.Actions | Format-List *

Write-Host "=== run_agent.ps1 全文关键段 ==="
$lines = Get-Content D:\MT4LAB\agent\run_agent.ps1
$lines | Select-String -Pattern "wait|Wait|CMD_WAIT|Instance|instance" | ForEach-Object { "$($_.LineNumber): $($_.Line)" }

Write-Host "=== 8041进程CMD_WAIT_SEC环境变量 ==="
$p8041 = (Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$env8041 = [System.Diagnostics.Process]::GetProcessById($p8041).StartInfo.EnvironmentVariables
if ($env8041.Keys -contains "CMD_WAIT_SEC") { "CMD_WAIT_SEC=$($env8041['CMD_WAIT_SEC'])" } else { "CMD_WAIT_SEC not in StartInfo (check WMI)" }

# Alternative: check via WMI env query
$procEnv = Get-WmiObject Win32_Process -Filter "ProcessId=$p8041" | Select-Object -ExpandProperty EnvironmentVariables -ErrorAction SilentlyContinue
Write-Host "WMI env: $procEnv"

Write-Host "=== agent配置文件(config.json/run_config.json等) ==="
Get-ChildItem D:\MT4LAB\agent -Filter "*.json" -ErrorAction SilentlyContinue | Select-Object Name | Format-Table
Get-ChildItem D:\MT4LAB\agent -Filter "*.ps1" -ErrorAction SilentlyContinue | Select-Object Name | Format-Table
