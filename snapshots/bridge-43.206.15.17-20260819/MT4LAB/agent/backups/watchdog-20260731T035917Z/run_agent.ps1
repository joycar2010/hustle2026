param([Parameter(Mandatory=$true)][ValidateSet('ic','exness')]$Instance, [switch]$Portable)
# QHBridge MT4 Agent 启动器(每实例一进程)。Phase C 用测试 key;Phase F 换 go 共享 key。
# 文件目录 = 用户实际使用的 appdata 实例(IC=5D49F47D / Exness=2191F4A3)的 MQL4\Files\qhbridge。
# EA 挂在哪个终端就往其数据目录写;用户用的是安装版(数据落 appdata)。
$AD = 'C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal'
$map = @{
  ic     = @{ port = 8041; wait = 30; files = "$AD\5D49F47D1EA1ECFC0DDC965B6D100AC5\MQL4\Files\qhbridge" }
  exness = @{ port = 8042; wait = 20;  files = "$AD\2191F4A3D14D7B4B1EBB84F924777883\MQL4\Files\qhbridge" }
}
$c = $map[$Instance]
if ($Portable) { $c.files = "D:\MT4LAB\terminals\$Instance\MQL4\Files\qhbridge" }  # portable cutover (default off)
# 幂等守卫:端口已在监听则退出(供每 N 分钟自愈触发,不重复起进程)
if (Get-NetTCPConnection -LocalPort $c.port -State Listen -ErrorAction SilentlyContinue) { exit 0 }
$env:API_KEY           = '<REDACTED_API_KEY>'   # QH 共享 key(Phase F 切源)
$env:INSTANCE_NAME     = "qhmt4-$Instance"
$env:TERMINAL_FILES_DIR = $c.files
$env:SERVICE_PORT      = "$($c.port)"
$env:CMD_WAIT_SEC      = "$(if ($c.wait) { $c.wait } else { 8 })"   # IC 146ms Ohio; raise SENDING window
$env:SYNC_WAIT_SEC     = "0.55"   # final result within budget, otherwise durable HTTP 202
Set-Location D:\MT4LAB\agent
New-Item -ItemType Directory -Force D:\MT4LAB\agent\logs | Out-Null
& D:\MT4LAB\agent\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port $c.port *>> "D:\MT4LAB\agent\logs\$Instance.log"
