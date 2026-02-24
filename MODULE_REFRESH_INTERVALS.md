# 系统模块刷新时间统计

## 📊 刷新间隔汇总表

| 模块名称 | 刷新间隔 | 文件位置 | 说明 |
|---------|---------|---------|------|
| **Dashboard 仪表盘** | 1秒 | Dashboard.vue | 价格数据刷新 |
| **Dashboard 仪表盘** | 1秒 | Dashboard.vue | 最后更新时间 |
| **点差数据表** | 1秒 | SpreadDataTable.vue | 实时点差数据 |
| **点差图表** | 1秒 | SpreadChart.vue | 盈利数据图表 |
| **策略面板** | 1秒 | StrategyPanel.vue | 策略状态更新 |
| **风险管理** | 5秒 | Risk.vue | 风险数据刷新 |
| **风险仪表盘** | 5秒 | RiskDashboard.vue | 风险指标更新 |
| **点差图表** | 5秒 | SpreadChart.vue (dashboard) | 点差历史数据 |
| **未平仓订单** | 5秒 | OpenOrders.vue | 订单列表刷新 |
| **手动交易** | 5秒 | ManualTrading.vue | 最近订单更新 |
| **日志管理** | 5秒 | System.vue | 交易统计日志 |
| **资产仪表盘** | 10秒 | AssetDashboard.vue | 资产数据刷新 |
| **账户状态面板** | 30秒 | AccountStatusPanel.vue | 账户信息更新 |

## 📈 按刷新频率分类

### ⚡ 高频刷新（1秒）
适用于需要实时监控的关键数据：
- Dashboard 价格数据
- 点差数据表
- 点差图表（盈利数据）
- 策略面板状态

**特点**：数据变化快，需要实时响应

### 🔄 中频刷新（5秒）
适用于重要但不需要极高实时性的数据：
- 风险管理数据
- 未平仓订单
- 手动交易订单
- 日志管理
- 点差历史数据

**特点**：平衡实时性和性能

### 🕐 低频刷新（10-30秒）
适用于变化较慢的数据：
- 资产仪表盘（10秒）
- 账户状态面板（30秒）

**特点**：减少服务器负载，数据变化慢

## 🎯 各页面刷新时间详情

### 1. Dashboard 页面 (/)
- **价格数据**：1秒
- **最后更新时间**：1秒
- **用途**：实时监控市场价格和点差

### 2. Trading 页面 (/trading)
- **点差数据表**：1秒
- **点差图表**：1秒
- **策略面板**：1秒
- **未平仓订单**：5秒
- **手动交易订单**：5秒
- **账户状态**：30秒
- **用途**：交易执行和监控

### 3. Risk 页面 (/risk)
- **风险数据**：5秒
- **用途**：风险指标监控

### 4. System 页面 (/system)
- **日志管理**：5秒
- **用途**：系统日志查看

### 5. Dashboard 组件
- **点差图表**：5秒
- **资产仪表盘**：10秒
- **用途**：数据可视化

## ⚙️ 性能优化建议

### 当前配置评估
✅ **合理的配置**：
- 关键交易数据使用1秒刷新（点差、价格）
- 监控数据使用5秒刷新（订单、风险）
- 静态数据使用30秒刷新（账户状态）

### 优化建议

1. **考虑使用WebSocket**
   - 对于1秒刷新的数据，可以改用WebSocket推送
   - 减少HTTP轮询开销
   - 提高实时性

2. **动态调整刷新频率**
   - 页面不可见时降低刷新频率
   - 使用 `document.visibilityState` 检测
   - 节省资源和带宽

3. **批量请求优化**
   - 合并多个1秒刷新的请求
   - 减少HTTP请求数量
   - 降低服务器负载

4. **缓存策略**
   - 对变化慢的数据增加缓存
   - 减少不必要的请求
   - 提升响应速度

## 📝 代码示例

### 当前实现（轮询）
```javascript
// 5秒刷新示例
setInterval(fetchRiskData, 5000)
```

### 优化建议（页面可见性检测）
```javascript
let refreshInterval = null
const ACTIVE_INTERVAL = 5000
const INACTIVE_INTERVAL = 30000

function startRefresh() {
  const interval = document.hidden ? INACTIVE_INTERVAL : ACTIVE_INTERVAL
  refreshInterval = setInterval(fetchData, interval)
}

document.addEventListener('visibilitychange', () => {
  clearInterval(refreshInterval)
  startRefresh()
})
```

### 优化建议（WebSocket）
```javascript
// 替代1秒轮询
const ws = new WebSocket('ws://localhost:8000/ws/prices')
ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  updatePrices(data)
}
```

## 🔍 监控指标

### 网络请求统计（估算）
假设所有模块同时运行：

**每分钟请求数**：
- 1秒刷新：60次 × 4个模块 = 240次
- 5秒刷新：12次 × 6个模块 = 72次
- 10秒刷新：6次 × 1个模块 = 6次
- 30秒刷新：2次 × 1个模块 = 2次

**总计**：约 320次/分钟

### 带宽估算
假设每次请求响应约10KB：
- 每分钟：320 × 10KB = 3.2MB
- 每小时：3.2MB × 60 = 192MB
- 每天：192MB × 24 = 4.6GB

## 📌 注意事项

1. **用户体验优先**
   - 关键交易数据保持高频刷新
   - 确保数据实时性

2. **性能平衡**
   - 避免过度刷新导致性能问题
   - 监控服务器负载

3. **错误处理**
   - 刷新失败时的重试机制
   - 避免无限重试

4. **清理机制**
   - 组件卸载时清除定时器
   - 避免内存泄漏

## 🎯 总结

当前系统的刷新时间配置整体合理：
- ✅ 关键数据（价格、点差）：1秒高频刷新
- ✅ 监控数据（订单、风险）：5秒中频刷新
- ✅ 静态数据（账户状态）：30秒低频刷新

建议优化方向：
1. 考虑引入WebSocket替代部分高频轮询
2. 实现页面可见性检测，动态调整刷新频率
3. 监控实际网络负载，根据需要调整
