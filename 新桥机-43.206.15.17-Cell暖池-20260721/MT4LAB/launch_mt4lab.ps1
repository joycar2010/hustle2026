# QHBridge MT4 Lab 终端启动器(幂等)。启动带 QHBridge EA 的安装版终端(数据落 appdata:
# IC=5D49F47D / Exness=2191F4A3,profile 已存 EA,启动自动挂载 + 自动登录)。
# 幂等:该 exe 已在跑则跳过(供 MT4LAB-Startup AtLogOn + 每5分钟自愈)。
$terminals = @(
  @{ name = 'ic';     exe = 'C:\Program Files (x86)\MetaTrader 4 IC Markets Global\terminal.exe' }
  @{ name = 'exness'; exe = 'C:\Program Files (x86)\MetaTrader 4 EXNESS\terminal.exe' }
)
foreach ($t in $terminals) {
  $run = Get-Process terminal -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $t.exe }
  if (-not $run) {
    Start-Process $t.exe -WorkingDirectory (Split-Path $t.exe -Parent)
    Start-Sleep 10
  }
}
