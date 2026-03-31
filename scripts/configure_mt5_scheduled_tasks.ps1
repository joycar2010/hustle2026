# MT5 任务计划程序配置脚本
# 配置 MT5 实例在用户登录时自动启动

param(
    [Parameter(Mandatory=$false)]
    [switch]$Remove
)

# 检查管理员权限
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[错误] 此脚本需要管理员权限运行" -ForegroundColor Red
    Read-Host "按 Enter 键退出"
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "MT5 任务计划程序配置" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# MT5 实例配置
$instances = @(
    @{
        Name = "MT5-System-Service"
        TaskName = "MT5-System-Service-AutoStart"
        Path = "C:\Program Files\MetaTrader 5\terminal64.exe"
        WorkingDir = "C:\Program Files\MetaTrader 5"
        Description = "Auto start MT5 System Service instance (8001) on user logon"
    },
    @{
        Name = "MT5-01"
        TaskName = "MT5-01-AutoStart"
        Path = "D:\MetaTrader 5-01\terminal64.exe"
        WorkingDir = "D:\MetaTrader 5-01"
        Description = "Auto start MT5-01 instance (8002) on user logon"
    }
)

if ($Remove) {
    # 删除任务
    Write-Host "删除任务计划..." -ForegroundColor Yellow
    Write-Host ""

    foreach ($instance in $instances) {
        Write-Host "处理: $($instance.Name)" -ForegroundColor Cyan
        try {
            $task = Get-ScheduledTask -TaskName $instance.TaskName -ErrorAction SilentlyContinue
            if ($task) {
                Unregister-ScheduledTask -TaskName $instance.TaskName -Confirm:$false
                Write-Host "  [成功] 任务已删除" -ForegroundColor Green
            } else {
                Write-Host "  [信息] 任务不存在" -ForegroundColor Gray
            }
        } catch {
            Write-Host "  [错误] 删除失败: $_" -ForegroundColor Red
        }
        Write-Host ""
    }
} else {
    # 创建任务
    Write-Host "创建任务计划..." -ForegroundColor Yellow
    Write-Host ""

    foreach ($instance in $instances) {
        Write-Host "处理: $($instance.Name)" -ForegroundColor Cyan
        Write-Host "  路径: $($instance.Path)" -ForegroundColor Gray

        # 检查 MT5 可执行文件是否存在
        if (-not (Test-Path $instance.Path)) {
            Write-Host "  [警告] MT5 可执行文件不存在，跳过" -ForegroundColor Yellow
            Write-Host ""
            continue
        }

        try {
            # 删除已存在的任务
            $existingTask = Get-ScheduledTask -TaskName $instance.TaskName -ErrorAction SilentlyContinue
            if ($existingTask) {
                Unregister-ScheduledTask -TaskName $instance.TaskName -Confirm:$false
                Write-Host "  [信息] 已删除旧任务" -ForegroundColor Gray
            }

            # 创建任务动作
            $Action = New-ScheduledTaskAction `
                -Execute $instance.Path `
                -Argument "/portable" `
                -WorkingDirectory $instance.WorkingDir

            # 创建触发器（用户登录时）
            $Trigger = New-ScheduledTaskTrigger `
                -AtLogOn `
                -User "Administrator"

            # 创建设置
            $Settings = New-ScheduledTaskSettingsSet `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -StartWhenAvailable `
                -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
                -RestartCount 3 `
                -RestartInterval (New-TimeSpan -Minutes 1)

            # 创建主体（以最高权限运行）
            $Principal = New-ScheduledTaskPrincipal `
                -UserId "Administrator" `
                -LogonType Interactive `
                -RunLevel Highest

            # 注册任务
            Register-ScheduledTask `
                -TaskName $instance.TaskName `
                -Action $Action `
                -Trigger $Trigger `
                -Settings $Settings `
                -Principal $Principal `
                -Description $instance.Description | Out-Null

            Write-Host "  [成功] 任务已创建" -ForegroundColor Green

            # 验证任务
            $task = Get-ScheduledTask -TaskName $instance.TaskName
            Write-Host "  状态: $($task.State)" -ForegroundColor Gray

        } catch {
            Write-Host "  [错误] 创建失败: $_" -ForegroundColor Red
        }

        Write-Host ""
    }
}

# 显示所有 MT5 相关任务
Write-Host "当前 MT5 任务计划:" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object { $_.TaskName -like "*MT5*" } | Select-Object TaskName, State, @{Name="NextRun";Expression={$_.NextRunTime}} | Format-Table -AutoSize

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "配置完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "说明:" -ForegroundColor Yellow
Write-Host "- MT5 将在 Administrator 用户登录时自动启动" -ForegroundColor Gray
Write-Host "- 如果 MT5 崩溃，将自动重启（最多 3 次）" -ForegroundColor Gray
Write-Host "- 可以通过任务计划程序查看和管理任务" -ForegroundColor Gray
Write-Host ""
Read-Host "按 Enter 键退出"
