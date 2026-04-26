# MT5 客户端状态检查脚本
# 用于检查 MT5 客户端的详细连接状态

param(
    [Parameter(Mandatory=$false)]
    [int]$Port = 8002
)

Write-Host "=== MT5 客户端状态检查 ===" -ForegroundColor Cyan
Write-Host "检查端口: $Port" -ForegroundColor Gray
Write-Host ""

# 1. 检查 Bridge 服务健康状态
Write-Host "1. 检查 Bridge 服务..." -ForegroundColor Yellow
try {
    $healthResponse = Invoke-RestMethod -Uri "http://localhost:$Port/health" -Method Get -TimeoutSec 5
    Write-Host "   状态: $($healthResponse.status)" -ForegroundColor Green
    Write-Host "   服务: $($healthResponse.service)" -ForegroundColor Gray
    Write-Host "   实例: $($healthResponse.instance)" -ForegroundColor Gray
    Write-Host "   MT5连接: $($healthResponse.mt5)" -ForegroundColor $(if ($healthResponse.mt5) { "Green" } else { "Red" })
} catch {
    Write-Host "   [错误] Bridge 服务未响应: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# 2. 检查 MT5 连接详情
Write-Host "2. 检查 MT5 连接详情..." -ForegroundColor Yellow
try {
    $statusResponse = Invoke-RestMethod -Uri "http://localhost:$Port/mt5/connection/status" -Method Get -TimeoutSec 5
    Write-Host "   连接状态: $($statusResponse.connected)" -ForegroundColor $(if ($statusResponse.connected) { "Green" } else { "Red" })
    if ($statusResponse.account) {
        Write-Host "   账号: $($statusResponse.account)" -ForegroundColor Gray
    }
    if ($statusResponse.server) {
        Write-Host "   服务器: $($statusResponse.server)" -ForegroundColor Gray
    }
    if ($statusResponse.error) {
        Write-Host "   错误: $($statusResponse.error)" -ForegroundColor Red
    }
} catch {
    Write-Host "   [警告] 无法获取连接详情: $_" -ForegroundColor Yellow
}

Write-Host ""

# 3. 检查账户信息
Write-Host "3. 检查账户信息..." -ForegroundColor Yellow
try {
    $accountResponse = Invoke-RestMethod -Uri "http://localhost:$Port/mt5/account/info" -Method Get -TimeoutSec 5
    Write-Host "   账号: $($accountResponse.login)" -ForegroundColor Gray
    Write-Host "   余额: $($accountResponse.balance)" -ForegroundColor Gray
    Write-Host "   净值: $($accountResponse.equity)" -ForegroundColor Gray
    Write-Host "   服务器: $($accountResponse.server)" -ForegroundColor Gray
} catch {
    Write-Host "   [警告] 无法获取账户信息: $_" -ForegroundColor Yellow
}

Write-Host ""

# 4. 检查 MT5 进程
Write-Host "4. 检查 MT5 进程..." -ForegroundColor Yellow
$instances = Invoke-RestMethod -Uri "http://localhost:9000/instances" -Method Get
$instance = $instances.instances | Where-Object { $_.port -eq $Port }

if ($instance) {
    $mt5Path = $instance.mt5_path
    $targetPath = [System.IO.Path]::GetFullPath($mt5Path).ToLower()

    $mt5Process = Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Where-Object {
        try {
            $procPath = $_.Path
            if ($procPath) {
                $procPath = [System.IO.Path]::GetFullPath($procPath).ToLower()
                return $procPath -eq $targetPath
            }
        } catch {}
        return $false
    }

    if ($mt5Process) {
        Write-Host "   进程ID: $($mt5Process.Id)" -ForegroundColor Gray
        Write-Host "   会话ID: $($mt5Process.SessionId)" -ForegroundColor Gray
        Write-Host "   窗口句柄: $($mt5Process.MainWindowHandle)" -ForegroundColor Gray
        Write-Host "   路径: $($mt5Process.Path)" -ForegroundColor Gray

        if ($mt5Process.SessionId -eq 0) {
            Write-Host "   [警告] MT5 在 Session 0 中运行，GUI 不可见" -ForegroundColor Yellow
        } elseif ($mt5Process.MainWindowHandle -eq 0) {
            Write-Host "   [警告] MT5 没有窗口句柄" -ForegroundColor Yellow
        } else {
            Write-Host "   [正常] MT5 在用户会话中运行，GUI 可见" -ForegroundColor Green
        }
    } else {
        Write-Host "   [错误] MT5 进程未运行" -ForegroundColor Red
    }
} else {
    Write-Host "   [错误] 未找到端口 $Port 的实例配置" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== 检查完成 ===" -ForegroundColor Cyan
