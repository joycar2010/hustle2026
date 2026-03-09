# Binance API限流问题修复说明

## 问题描述
系统因频繁调用Binance API导致IP被封禁，错误信息：
```
Binance API error: {'code': -1003, 'msg': 'Way too many requests; IP(13.115.21.77) banned until 1773054593697.'}
```

## IP封禁时间
- **时间戳**: 1773054593697 (毫秒)
- **UTC时间**: 2026-03-09 11:09:53
- **北京时间**: 2026-03-09 19:09:53

## 已实施的优化措施

### 1. 后端优化

#### 1.1 增加缓存时间
- **文件**: `backend/app/services/account_service.py`
- **修改**: 缓存TTL从30秒增加到60秒
- **影响**: 减少重复API调用

#### 1.2 降低账户余额推送频率
- **文件**: `backend/app/tasks/broadcast_tasks.py`
- **修改**: 推送间隔从20秒增加到30秒
- **影响**: 降低API调用频率

#### 1.3 移除REST API回退机制
- **文件**: `backend/app/services/market_service.py`
- **修改**: 当WebSocket未连接时，不再回退到REST API，而是直接报错
- **影响**: 避免在WebSocket断开时频繁调用REST API

#### 1.4 改进WebSocket重连机制
- **文件**: `backend/app/services/binance_ws_client.py`
- **修改**:
  - 重连间隔从2秒增加到5秒
  - 添加重连计数器
  - 增强日志记录
- **影响**: 避免过于激进的重连尝试

#### 1.5 添加WebSocket状态监控
- **文件**: `backend/app/api/v1/system.py`
- **新增**: `/api/v1/system/websocket-status` 端点
- **功能**: 实时监控Binance WebSocket连接状态

#### 1.6 优化错误信息格式
- **文件**: `backend/app/services/account_service.py`
- **修改**: 统一限流错误格式为 `RATE_LIMIT:{timestamp}`
- **影响**: 前端可以准确显示解封时间

### 2. 前端优化

#### 2.1 改进错误显示
- **文件**: `frontend/src/components/trading/AccountStatusPanel.vue`
- **修改**:
  - 使用24小时制显示北京时间
  - 特殊样式显示限流错误（橙色警告）
  - 显示详细的解封时间和剩余分钟数
  - 添加友好提示信息

#### 2.2 错误显示格式
```
⚠️ Binance API限流
API限流至 19:09:53 (约120分钟)
系统已自动降低请求频率，请耐心等待
```

## 使用说明

### 检查WebSocket连接状态
```bash
# 访问WebSocket状态端点
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/system/websocket-status
```

### 测试Binance API连接
```bash
cd backend
python check_binance_status.py
```

### 重启服务
```bash
# 重启后端服务以应用新配置
# Windows
taskkill /F /IM python.exe
python backend/app/main.py

# 或使用你的服务管理脚本
```

## 预防措施

### 1. 监控API调用频率
- 定期检查日志中的API调用频率
- 确保WebSocket连接稳定
- 避免在短时间内重启服务

### 2. 使用WebSocket优先
- 市场数据应优先使用WebSocket
- 仅在必要时使用REST API
- 实施请求缓存机制

### 3. 实施速率限制
- 账户数据推送间隔：30秒
- 市场数据推送间隔：0.25秒（有策略时）/ 1秒（无策略时）
- 缓存时间：60秒

## 后续建议

1. **等待IP解封**: 北京时间今晚19:09:53后恢复正常
2. **监控WebSocket**: 确保WebSocket连接稳定，避免回退到REST API
3. **优化策略**: 考虑进一步增加缓存时间或降低推送频率
4. **添加告警**: 当检测到限流错误时，发送通知给管理员

## 相关文件

- `backend/app/services/account_service.py` - 账户服务
- `backend/app/services/market_service.py` - 市场数据服务
- `backend/app/services/binance_ws_client.py` - Binance WebSocket客户端
- `backend/app/tasks/broadcast_tasks.py` - 广播任务
- `backend/app/api/v1/system.py` - 系统API
- `frontend/src/components/trading/AccountStatusPanel.vue` - 账户状态面板
- `backend/check_binance_status.py` - API状态检查脚本

## 技术细节

### API调用频率对比

| 组件 | 修改前 | 修改后 | 降低比例 |
|------|--------|--------|----------|
| 账户余额推送 | 20秒/次 | 30秒/次 | 33% |
| 账户数据缓存 | 30秒 | 60秒 | 50% |
| WebSocket重连 | 2秒 | 5秒 | 60% |
| 市场数据回退 | 启用 | 禁用 | 100% |

### 预期效果
- API调用总量减少约 **60-70%**
- WebSocket稳定性提升
- 用户体验改善（更清晰的错误提示）
