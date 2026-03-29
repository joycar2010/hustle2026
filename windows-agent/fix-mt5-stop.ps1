# Windows Agent 修复脚本 - 添加 MT5 客户端停止功能
# 在 MT5 服务器上运行

Write-Host "开始修复 Windows Agent..." -ForegroundColor Green

# 1. 停止 Agent
Write-Host "[1/5] 停止当前 Agent..."
taskkill /F /IM python.exe 2>$null
Start-Sleep -Seconds 3

# 2. 备份
Write-Host "[2/5] 备份当前版本..."
cd D:\hustle-agent
Copy-Item agent.py agent.py.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')

# 3. 读取当前文件
$content = Get-Content agent.py -Raw

# 4. 添加 stop_mt5_client 函数（在 get_process_by_port 后面）
Write-Host "[3/5] 添加 MT5 客户端停止功能..."

$stopMt5Function = @'


def stop_mt5_client(deploy_path: str) -> bool:
    """停止与部署路径关联的 MT5 客户端"""
    stopped = False
    try:
        deploy_path_normalized = Path(deploy_path).resolve()
        for proc in psutil.process_iter(['name', 'exe', 'cwd']):
            try:
                if proc.info['name'] and 'terminal64.exe' in proc.info['name'].lower():
                    proc_cwd = proc.info.get('cwd')
                    if proc_cwd:
                        proc_cwd_path = Path(proc_cwd).resolve()
                        if deploy_path_normalized in proc_cwd_path.parents or proc_cwd_path == deploy_path_normalized:
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except psutil.TimeoutExpired:
                                proc.kill()
                            stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception:
        pass
    return stopped
'@

# 在 get_process_by_port 函数后插入
if ($content -match '(def get_process_by_port.*?return None)') {
    $content = $content -replace '(def get_process_by_port.*?return None)', "`$1$stopMt5Function"
}

# 5. 修改 stop_instance 函数
Write-Host "[4/5] 修改停止实例函数..."

$newStopFunction = @'
@app.post("/instances/{port}/stop")
async def stop_instance(port: int):
    """停止实例（包括 MT5 桥接服务和 MT5 客户端）"""
    instances = load_instances()
    port_str = str(port)

    if port_str not in instances:
        raise HTTPException(status_code=404, detail=f"Instance on port {port} not found")

    config = instances[port_str]
    stopped_services = []

    # 1. 停止 MT5 桥接服务
    proc = get_process_by_port(port)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=10)
            stopped_services.append("bridge")
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            stopped_services.append("bridge")

    # 2. 停止 MT5 客户端
    if stop_mt5_client(config["deploy_path"]):
        stopped_services.append("mt5client")

    return {"message": "Instance stopped", "port": port, "stopped": stopped_services}
'@

# 替换 stop_instance 函数
$pattern = '@app\.post\("/instances/\{port\}/stop"\).*?async def stop_instance.*?return \{.*?\}'
$content = $content -replace $pattern, $newStopFunction -replace '(?s)@app\.post\("/instances/\{port\}/stop"\).*?(?=@app\.post\("/instances/\{port\}/restart"\)|@app\.get)', $newStopFunction

Set-Content agent.py $content

# 6. 启动 Agent
Write-Host "[5/5] 启动 Agent..."
Start-Process python -ArgumentList "agent.py" -WindowStyle Hidden
Start-Sleep -Seconds 5

# 7. 验证
Write-Host "`n验证 Agent 状态..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:9000/" -UseBasicParsing -TimeoutSec 5
    Write-Host "✓ Agent 运行正常: $($response.Content)" -ForegroundColor Green
} catch {
    Write-Host "✗ Agent 启动失败" -ForegroundColor Red
}

Write-Host "`n修复完成！" -ForegroundColor Green
Write-Host "请在前端测试停止和重启功能" -ForegroundColor Yellow
