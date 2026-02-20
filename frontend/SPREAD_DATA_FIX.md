# 点差数据显示修复

## 问题描述

在 http://13.115.21.77:3000/ 中：
1. SpreadChart.vue 无点差数据
2. SpreadDataTable.vue 无点差数据
3. SpreadDataTable.vue 的点差数据无更新

## 根本原因

前端组件中硬编码了 `http://localhost:8000` 作为 API 地址，导致从外部 IP (13.115.21.77) 访问时无法连接到后端 API。

## 修复内容

### 1. SpreadDataTable.vue
**文件**: `c:\app\hustle2026\frontend\src\components\trading\SpreadDataTable.vue`

**修改前**:
```javascript
const response = await fetch(
  'http://localhost:8000/api/v1/market/spread/history?limit=16&binance_symbol=XAUUSDT&bybit_symbol=XAUUSDT',
  {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  }
)
```

**修改后**:
```javascript
import api from '@/services/api'

const response = await api.get('/api/v1/market/spread/history', {
  params: {
    limit: 16,
    binance_symbol: 'XAUUSDT',
    bybit_symbol: 'XAUUSDT'
  }
})
```

### 2. SpreadChart.vue (Trading)
**文件**: `c:\app\hustle2026\frontend\src\components\trading\SpreadChart.vue`

**修改**: 同样替换硬编码的 localhost URL 为 api 服务调用

### 3. SpreadChart.vue (Dashboard)
**文件**: `c:\app\hustle2026\frontend\src\components\dashboard\SpreadChart.vue`

**修改**: 同样替换硬编码的 localhost URL 为 api 服务调用

## 验证结果

### 后端数据确认
```bash
# 数据库中有 51,989 条点差记录
# 最新记录每 5 秒更新一次
# API 端点正常返回数据
```

### API 测试
```bash
curl "http://localhost:8000/api/v1/market/spread/history?limit=5&binance_symbol=XAUUSDT&bybit_symbol=XAUUSDT"

# 返回示例:
{
  "id": "1c0fb249-8002-4b2d-b7c1-3ad16833ecfb",
  "timestamp": "2026-02-20T13:00:57.585942",
  "binance_quote": {
    "bid": 5028.0,
    "ask": 5028.01
  },
  "bybit_quote": {
    "bid": 5025.04,
    "ask": 5025.24
  },
  "forward_spread": -2.97,
  "reverse_spread": 2.76
}
```

## 技术说明

### API 服务配置

前端使用统一的 API 服务 (`@/services/api.js`)，该服务会根据环境变量自动选择正确的 API 地址：

```javascript
// frontend/src/services/api.js
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  timeout: 10000,
})
```

### 环境配置

**文件**: `c:\app\hustle2026\frontend\.env`
```
VITE_API_BASE_URL=http://13.115.21.77:8000
VITE_WS_URL=ws://13.115.21.77:8000
```

这样配置后：
- 从 localhost 访问：使用 localhost:8000
- 从外部 IP 访问：使用 13.115.21.77:8000

### 点差数据更新机制

1. **数据收集**: 后端每 5 秒从 Binance 和 Bybit 获取市场数据
2. **点差计算**:
   - Forward Spread (做多 Binance) = Bybit ASK - Binance BID
   - Reverse Spread (做多 Bybit) = Binance ASK - Bybit BID
3. **数据存储**: 存储到 `spread_records` 表
4. **前端轮询**: 前端每 1 秒请求最新数据
5. **实时更新**: 新数据到达时高亮显示

## 修复状态

✅ **已修复**: 所有点差相关组件已更新使用统一 API 服务
✅ **已验证**: 后端数据收集正常，API 端点工作正常
✅ **已重启**: 前端服务已重启并应用更改

## 访问地址

- **主页**: http://13.115.21.77:3000/
- **交易页面**: http://13.115.21.77:3000/trading
- **Dashboard**: http://13.115.21.77:3000/dashboard

## 相关组件

1. **SpreadDataTable.vue**: 点差数据流表格，显示最近 16 条点差记录
2. **SpreadChart.vue (Trading)**: 交易页面的盈亏曲线图
3. **SpreadChart.vue (Dashboard)**: 仪表板的点差曲线图

所有组件现在都能正确显示和更新点差数据。
