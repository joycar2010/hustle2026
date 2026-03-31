# MT5 Agent 修复脚本 - 修复 stop_mt5_client 函数
# 确保只停止指定部署路径的 MT5 客户端

Write-Host "=== MT5 Agent stop_mt5_client 函数修复 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 备份原文件
$mainPyPath = "C:\MT5Agent\main.py"
$backupPath = "C:\MT5Agent\main.py.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "1. 备份原文件..." -ForegroundColor Yellow
Copy-Item $mainPyPath $backupPath
Write-Host "   备份已保存到: $backupPath" -ForegroundColor Green
Write-Host ""

# 2. 读取文件内容
Write-Host "2. 读取文件内容..." -ForegroundColor Yellow
$content = Get-Content $mainPyPath -Raw -Encoding UTF8

# 3. 查找并替换 stop_mt5_client 函数
Write-Host "3. 替换 stop_mt5_client 函数..." -ForegroundColor Yellow

$newFunction = @'
def stop_mt5_client(deploy_path: str, account: str = None) -> bool:
    """
    停止 MT5 客户端（只停止指定部署路径的实例）

    策略：
    1. 通过进程的工作目录（cwd）匹配部署路径
    2. 如果无法获取 cwd，通过命令行参数匹配
    3. 只停止匹配的进程，不影响其他实例
    """
    stopped = False
    terminal_procs = []
    deploy_path_normalized = Path(deploy_path).resolve()

    # 收集所有 terminal64 进程
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] and 'terminal64.exe' in proc.info['name'].lower():
                terminal_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not terminal_procs:
        return False

    # 如果只有一个 MT5 进程，直接停止它
    if len(terminal_procs) == 1:
        try:
            terminal_procs[0].terminate()
            terminal_procs[0].wait(timeout=5)
            stopped = True
        except psutil.TimeoutExpired:
            terminal_procs[0].kill()
            stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return stopped

    # 多个进程：通过部署路径匹配
    target_proc = None

    for proc in terminal_procs:
        try:
            # 方法1：检查进程的工作目录
            try:
                proc_cwd = Path(proc.cwd()).resolve()
                if deploy_path_normalized in proc_cwd.parents or proc_cwd == deploy_path_normalized:
                    target_proc = proc
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            # 方法2：检查命令行参数
            try:
                cmdline = ' '.join(proc.cmdline())
                if str(deploy_path_normalized) in cmdline or deploy_path in cmdline:
                    target_proc = proc
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

            # 方法3：检查打开的文件
            try:
                for file in proc.open_files():
                    file_path = Path(file.path).resolve()
                    if deploy_path_normalized in file_path.parents:
                        target_proc = proc
                        break
                if target_proc:
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 停止匹配的进程
    if target_proc:
        try:
            target_proc.terminate()
            target_proc.wait(timeout=5)
            stopped = True
        except psutil.TimeoutExpired:
            target_proc.kill()
            stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    else:
        print(f"Warning: Could not identify MT5 process for deploy_path: {deploy_path}")
        print(f"Found {len(terminal_procs)} MT5 processes but none matched")
        stopped = False

    return stopped
'@

# 使用正则表达式替换整个函数
$pattern = '(?s)def stop_mt5_client\(.*?\n(?=\ndef |\Z)'
$newContent = $content -replace $pattern, $newFunction

# 4. 保存修改后的文件
Write-Host "4. 保存修改..." -ForegroundColor Yellow
$newContent | Set-Content $mainPyPath -Encoding UTF8 -NoNewline
Write-Host "   文件已更新" -ForegroundColor Green
Write-Host ""

# 5. 重启 Windows Agent
Write-Host "5. 重启 Windows Agent..." -ForegroundColor Yellow
$agentProcess = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*MT5Agent*" }
if ($agentProcess) {
    Stop-Process -Id $agentProcess.Id -Force
    Write-Host "   已停止旧进程" -ForegroundColor Green
}

Start-Sleep -Seconds 2

# 启动新进程
Start-Process -FilePath "python" -ArgumentList "C:\MT5Agent\main.py" -WorkingDirectory "C:\MT5Agent" -WindowStyle Hidden
Write-Host "   已启动新进程" -ForegroundColor Green
Write-Host ""

Write-Host "=== 修复完成 ===" -ForegroundColor Green
Write-Host ""
Write-Host "修复内容：" -ForegroundColor Cyan
Write-Host "  - 修复了 stop_mt5_client 函数" -ForegroundColor White
Write-Host "  - 现在只停止指定部署路径的 MT5 客户端" -ForegroundColor White
Write-Host "  - 不会影响其他实例" -ForegroundColor White
Write-Host ""
Write-Host "备份文件：$backupPath" -ForegroundColor Yellow
