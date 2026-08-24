$ErrorActionPreference = 'Stop'

$tasks = Get-ScheduledTask | Where-Object {
    $_.TaskName -like '*MT4LAB*' -or $_.TaskName -like '*no123*' -or
    $_.TaskName -like '*Watchdog*'
} | Select-Object TaskName, State, TaskPath, @{
    Name = 'Actions'; Expression = { @($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) }
}, @{
    Name = 'Triggers'; Expression = { @($_.Triggers | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 5 }) }
}

$terminals = Get-CimInstance Win32_Process -Filter "Name='terminal.exe'" | Where-Object {
    $_.ExecutablePath -like 'D:\MT4LAB\terminals\*'
} | Select-Object ProcessId, ExecutablePath, CommandLine, @{
    Name = 'StartTime'; Expression = { (Get-Process -Id $_.ProcessId).StartTime.ToUniversalTime().ToString('o') }
}

[ordered]@{
    tasks = @($tasks)
    terminals = @($terminals)
    startup_task_info = Get-ScheduledTaskInfo -TaskName 'MT4LAB-Startup'
    watchdog_task_info = Get-ScheduledTaskInfo -TaskName 'QH-MT4-Agent-Watchdog' -ErrorAction SilentlyContinue
    launcher = Get-Content -LiteralPath 'D:\MT4LAB\launch_mt4lab_portable.ps1' -Raw
    watchdog_log_tail = @(Get-Content -LiteralPath 'D:\MT4LAB\agent\watchdog.log' -Tail 40 -ErrorAction SilentlyContinue)
    profiles = [ordered]@{
        ic = @(Get-ChildItem -LiteralPath 'D:\MT4LAB\terminals\ic\profiles' -Force | Select-Object Name, FullName)
        exness = @(Get-ChildItem -LiteralPath 'D:\MT4LAB\terminals\exness\profiles' -Force | Select-Object Name, FullName)
    }
} | ConvertTo-Json -Depth 8 -Compress
