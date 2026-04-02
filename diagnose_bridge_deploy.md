# Bridge 部署 422 错误诊断指南

## 问题描述
部署 Bridge 时遇到 422 错误：`Client error '422 Unprocessable Entity'`

## 诊断步骤

### 1. 检查 Windows Agent 服务状态

在 Windows 服务器上执行：
```powershell
# 检查服务状态
sc query MT5Agent

# 查看服务日志
Get-Content C:\MT5Agent\logs\agent.log -Tail 100

# 如果服务未运行，重启服务
nssm restart MT5Agent
```

### 2. 测试 Windows Agent API

在任意机器上执行（或使用 Postman）：
```bash
curl -X POST http://172.31.14.113:8765/bridge/deploy \
  -H "X-API-Key: OQ6bUimHZDmXEZzJKE" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "test-service",
    "mt5_login": "123456",
    "mt5_password": "test123",
    "mt5_server": "Test-Server",
    "mt5_path": "D:\\MetaTrader 5-01\\terminal64.exe",
    "service_port": 8888
  }'
```

**预期结果**：
- 如果返回 422，说明参数验证失败
- 如果返回 400，说明目录已存在或其他业务错误
- 如果返回 200，说明 API 正常

### 3. 检查 main_v3.py 是否正确更新

在 Windows 服务器上执行：
```powershell
# 检查文件修改时间
Get-Item C:\MT5Agent\main_v3.py | Select-Object LastWriteTime

# 检查文件内容是否包含 BridgeDeployRequest
Select-String -Path C:\MT5Agent\main_v3.py -Pattern "BridgeDeployRequest"
```

**预期结果**：
- 文件应该在最近几分钟内被修改
- 应该能找到 `BridgeDeployRequest` 类定义

### 4. 手动重启 Windows Agent

```powershell
# 停止服务
nssm stop MT5Agent

# 等待 5 秒
Start-Sleep -Seconds 5

# 启动服务
nssm start MT5Agent

# 检查服务状态
sc query MT5Agent
```

### 5. 检查 Python 依赖

在 Windows 服务器上执行：
```powershell
cd C:\MT5Agent
python -c "from pydantic import BaseModel; print('Pydantic OK')"
```

**预期结果**：应该输出 `Pydantic OK`

### 6. 查看详细错误信息

在 Windows 服务器上执行：
```powershell
# 实时查看日志
Get-Content C:\MT5Agent\logs\agent.log -Wait -Tail 50
```

然后在浏览器中尝试部署，观察日志输出。

## 可能的问题和解决方案

### 问题 1：服务未正确重启
**症状**：文件已更新但仍然 422 错误
**解决**：手动停止并启动服务（不要用 restart）

### 问题 2：Pydantic 模型定义错误
**症状**：日志中显示参数验证失败
**解决**：检查 BridgeDeployRequest 模型定义是否正确

### 问题 3：后端发送的数据格式不对
**症状**：后端日志显示发送成功，但 Windows Agent 返回 422
**解决**：检查后端发送的 JSON 格式

### 问题 4：API Key 不匹配
**症状**：返回 401 而不是 422
**解决**：检查 API Key 配置

## 快速修复脚本

在 Windows 服务器上创建并运行此脚本：

```powershell
# fix_bridge_deploy.ps1

Write-Host "=== Bridge 部署问题修复脚本 ===" -ForegroundColor Green

# 1. 停止服务
Write-Host "`n1. 停止 MT5Agent 服务..." -ForegroundColor Yellow
nssm stop MT5Agent
Start-Sleep -Seconds 3

# 2. 备份当前文件
Write-Host "`n2. 备份当前文件..." -ForegroundColor Yellow
Copy-Item C:\MT5Agent\main_v3.py C:\MT5Agent\main_v3.py.backup -Force

# 3. 检查文件内容
Write-Host "`n3. 检查 BridgeDeployRequest 是否存在..." -ForegroundColor Yellow
$hasModel = Select-String -Path C:\MT5Agent\main_v3.py -Pattern "class BridgeDeployRequest" -Quiet
if ($hasModel) {
    Write-Host "   ✓ BridgeDeployRequest 模型已找到" -ForegroundColor Green
} else {
    Write-Host "   ✗ BridgeDeployRequest 模型未找到！" -ForegroundColor Red
    Write-Host "   请重新复制 main_v3.py 文件" -ForegroundColor Red
    exit 1
}

# 4. 启动服务
Write-Host "`n4. 启动 MT5Agent 服务..." -ForegroundColor Yellow
nssm start MT5Agent
Start-Sleep -Seconds 3

# 5. 检查服务状态
Write-Host "`n5. 检查服务状态..." -ForegroundColor Yellow
$status = sc query MT5Agent | Select-String "STATE"
Write-Host "   $status"

# 6. 测试 API
Write-Host "`n6. 测试 API 连接..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8765/health" -Headers @{"X-API-Key"="OQ6bUimHZDmXEZzJKE"} -UseBasicParsing
    Write-Host "   ✓ API 连接正常" -ForegroundColor Green
} catch {
    Write-Host "   ✗ API 连接失败: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== 修复完成 ===" -ForegroundColor Green
Write-Host "请在浏览器中重新尝试部署 Bridge 服务" -ForegroundColor Cyan
```

## 联系信息

如果以上步骤都无法解决问题，请提供以下信息：
1. Windows Agent 日志最后 100 行
2. 后端日志中的错误信息
3. 浏览器控制台的完整错误信息
4. `sc query MT5Agent` 的输出
