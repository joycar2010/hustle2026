# 延迟删除脚本 - 在系统启动时删除被锁定的目录
# 将此脚本添加到启动任务

$dirsToDelete = @(
    "D:\hustle-agent",
    "D:\hustle-mt5"
)

Write-Host "Delayed Directory Deletion Script" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

foreach ($dir in $dirsToDelete) {
    if (Test-Path $dir) {
        try {
            Write-Host "Attempting to delete: $dir" -ForegroundColor Yellow
            Remove-Item -Path $dir -Recurse -Force -ErrorAction Stop
            Write-Host "  SUCCESS: $dir deleted" -ForegroundColor Green
        } catch {
            Write-Host "  FAILED: $dir is locked - $($_.Exception.Message)" -ForegroundColor Red

            # 创建批处理文件在下次启动时删除
            $batFile = "C:\Windows\Temp\delete_$($dir.Replace('\','_').Replace(':','')).bat"
            $batContent = @"
@echo off
timeout /t 10 /nobreak
rd /s /q "$dir"
if exist "$dir" (
    echo Failed to delete $dir
) else (
    echo Successfully deleted $dir
    del "%~f0"
)
"@
            $batContent | Out-File -FilePath $batFile -Encoding ASCII -Force

            # 创建启动任务
            $taskName = "DeleteLockedDir_$($dir.Replace('\','_').Replace(':',''))"
            $action = New-ScheduledTaskAction -Execute $batFile
            $trigger = New-ScheduledTaskTrigger -AtStartup
            $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

            try {
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
                Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
                Write-Host "  SCHEDULED: Will delete on next reboot" -ForegroundColor Yellow
            } catch {
                Write-Host "  ERROR: Failed to schedule deletion - $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "SKIP: $dir does not exist" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "=================================" -ForegroundColor Cyan
Write-Host "Deletion script completed" -ForegroundColor Green
Write-Host ""
Write-Host "Note: Locked directories will be deleted on next system reboot" -ForegroundColor Yellow
Write-Host ""
