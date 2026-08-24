[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$baseDir = 'D:\MT4LAB\agent'
$watchdog = Join-Path $baseDir 'mt4_agent_watchdog.ps1'
if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "Missing watchdog script: $watchdog"
}

foreach ($taskName in 'MT4LAB-Agent-ic','MT4LAB-Agent-exness') {
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        throw "Missing scheduled task: $taskName"
    }
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    Set-ScheduledTask -TaskName $taskName -Trigger $startupTrigger -Settings $settings | Out-Null
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $watchdog)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName 'QH-MT4-Agent-Watchdog' -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName 'QH-MT4-Agent-Watchdog'

Get-ScheduledTask -TaskName 'MT4LAB-Agent-ic','MT4LAB-Agent-exness','QH-MT4-Agent-Watchdog' |
    Select-Object TaskName,State,@{Name='ExecutionTimeLimit';Expression={$_.Settings.ExecutionTimeLimit}},
        @{Name='RestartCount';Expression={$_.Settings.RestartCount}},
        @{Name='RestartInterval';Expression={$_.Settings.RestartInterval}}
