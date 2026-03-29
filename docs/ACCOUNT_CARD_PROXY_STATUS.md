# 账户卡片代理IP状态显示和按钮大小调整

## 实施日期
2026-03-16

## 功能概述
在左侧栏账户卡片中添加代理IP运行状态显示，并统一MT5和Binance账户的功能按钮大小。

## 实施内容

### 1. 代理IP状态显示

#### 显示位置
在账户卡片标题下方，平台名称和激活状态之间，新增代理IP运行状态行。

#### 显示内容
```
代理: 192.168.1.100:7890 (85/100, 120ms)
```

显示信息包括：
- 代理地址和端口
- 健康度评分（0-100）
- 平均延迟（毫秒）

#### 状态指示灯
- **绿色**: 健康度 ≥ 80
- **黄色**: 健康度 ≥ 50
- **红色**: 健康度 < 50
- **灰色**: 直连（未使用代理）

#### 数据结构
```javascript
accountProxies = {
  "account_id_platform_id": {
    host: "192.168.1.100",
    port: 7890,
    health_score: 85,
    avg_latency_ms: 120,
    platform_id: 1
  }
}
```

### 2. 按钮大小统一

#### 修改内容
为所有功能按钮添加 `whitespace-nowrap` 类，确保按钮文字不换行，保持一致的大小。

#### 按钮样式
```html
<button class="px-1.5 py-0.5 text-[10px] rounded transition-colors whitespace-nowrap">
  连接/断开/禁用
</button>
```

### 3. 技术实现

#### 新增状态变量
```javascript
const accountProxies = ref({})
let proxyRefreshTimer = null
```

#### 新增函数

**fetchProxyStatus()**
- 为每个账户的每个平台获取代理状态
- 调用 `/api/v1/accounts/{account_id}/proxy/{platform_id}`
- 存储到 `accountProxies` 对象中
- 404错误（未绑定代理）会被忽略

**getProxyStatus(account)**
- 根据账户ID和平台ID获取代理状态
- 返回代理数据或 null

**getProxyStatusColor(account)**
- 返回状态指示灯颜色类
- 绿色/黄色/红色/灰色

**getProxyStatusTextColor(account)**
- 返回状态文字颜色类
- 与指示灯颜色对应

**getProxyStatusText(account)**
- 返回代理状态文字
- 格式: `host:port (health/100, latencyms)`
- 直连时显示: `直连`

#### 刷新机制
- 初始加载: `fetchAccountData()` 完成后调用 `fetchProxyStatus()`
- 定时刷新: 每30秒刷新一次代理状态
- 清理: 组件卸载时清除定时器

### 4. 视觉效果

#### 账户卡片布局（修改后）
```
┌─────────────────────────────────┐
│ ● 主账户                    [连接][禁用] │
│ Binance                              │
│ ● 代理: 192.168.1.100:7890 (85/100, 120ms) │
│ 已激活                               │
│ 多头强平价: 2650.00                  │
│ 空头强平价: 2750.00                  │
├─────────────────────────────────┤
│ 账户总资产: 10,000.00 USDT          │
│ 可用总资产: 8,500.00 USDT           │
│ ...                                 │
└─────────────────────────────────┘
```

#### 状态示例

**健康代理（绿色）**
```
● 代理: 192.168.1.100:7890 (85/100, 120ms)
```

**警告代理（黄色）**
```
● 代理: 192.168.1.100:7890 (65/100, 250ms)
```

**异常代理（红色）**
```
● 代理: 192.168.1.100:7890 (30/100, 500ms)
```

**直连（灰色）**
```
● 代理: 直连
```

### 5. API调用

#### 获取账户代理状态
```
GET /api/v1/accounts/{account_id}/proxy/{platform_id}

Response:
{
  "proxy_id": 1,
  "host": "192.168.1.100",
  "port": 7890,
  "proxy_type": "http",
  "health_score": 85,
  "avg_latency_ms": 120,
  "status": "active",
  "provider": "local"
}
```

#### 错误处理
- 404: 账户未绑定代理，不显示代理状态
- 其他错误: 记录到控制台，不影响账户卡片显示

### 6. 性能优化

#### 批量获取
- 在 `fetchAccountData()` 完成后统一获取所有账户的代理状态
- 避免单独为每个账户发起请求

#### 缓存策略
- 代理状态缓存在 `accountProxies` 对象中
- 30秒刷新一次，减少API调用

#### 错误容忍
- 代理状态获取失败不影响账户数据显示
- 404错误（未绑定代理）静默处理

### 7. 按钮大小统一

#### 问题
MT5账户和Binance账户的功能按钮大小不一致，可能是因为文字长度不同导致换行。

#### 解决方案
添加 `whitespace-nowrap` 类，强制按钮文字不换行，保持一致的宽度和高度。

#### 修改前
```html
<button class="px-1.5 py-0.5 text-[10px] rounded transition-colors">
  连接
</button>
```

#### 修改后
```html
<button class="px-1.5 py-0.5 text-[10px] rounded transition-colors whitespace-nowrap">
  连接
</button>
```

## 文件修改清单

### 修改的文件
`frontend/src/components/trading/AccountStatusPanel.vue`

#### 模板部分
1. 在账户标题下方添加代理状态显示
2. 为功能按钮添加 `whitespace-nowrap` 类

#### 脚本部分
1. 新增 `accountProxies` 状态变量
2. 新增 `proxyRefreshTimer` 定时器变量
3. 新增 `fetchProxyStatus()` 函数
4. 新增 `getProxyStatus()` 函数
5. 新增 `getProxyStatusColor()` 函数
6. 新增 `getProxyStatusTextColor()` 函数
7. 新增 `getProxyStatusText()` 函数
8. 修改 `fetchAccountData()` 调用 `fetchProxyStatus()`
9. 修改 `onMounted()` 添加定时刷新
10. 修改 `onUnmounted()` 清理定时器

## 使用场景

### 场景1：账户使用健康代理
- 显示绿色指示灯
- 显示代理地址、健康度、延迟
- 用户可以快速了解代理运行良好

### 场景2：账户使用警告代理
- 显示黄色指示灯
- 健康度在50-80之间
- 提示用户代理可能需要关注

### 场景3：账户使用异常代理
- 显示红色指示灯
- 健康度低于50
- 提示用户代理存在问题，可能需要更换

### 场景4：账户直连（未使用代理）
- 显示灰色指示灯
- 显示"直连"文字
- 表示账户使用本地IP访问交易所

### 场景5：代理状态获取失败
- 不显示代理状态行
- 不影响账户其他信息显示
- 错误记录到控制台

## 测试建议

1. 测试有代理绑定的账户显示
2. 测试无代理绑定的账户显示
3. 测试不同健康度的代理颜色显示
4. 测试代理状态定时刷新
5. 测试MT5和Binance账户按钮大小一致性
6. 测试代理状态API失败时的容错
7. 测试多个账户同时显示代理状态

## 后续优化建议

1. **代理状态点击交互**
   - 点击代理状态可以快速切换代理
   - 显示代理详细信息弹窗

2. **代理健康度趋势**
   - 显示代理健康度的历史趋势
   - 用小图表展示最近的健康度变化

3. **代理告警**
   - 当代理健康度低于阈值时高亮显示
   - 发送通知提醒用户

4. **批量代理管理**
   - 在账户卡片中快速切换代理
   - 批量更新多个账户的代理

5. **代理使用统计**
   - 显示代理的使用次数
   - 显示代理的成功率

## 总结

成功在左侧栏账户卡片中集成代理IP运行状态显示，并统一了MT5和Binance账户的功能按钮大小。实现了：
- ✅ 代理状态实时显示（地址、健康度、延迟）
- ✅ 状态指示灯（绿/黄/红/灰）
- ✅ 30秒定时刷新代理状态
- ✅ 直连模式显示
- ✅ 按钮大小统一（whitespace-nowrap）
- ✅ 错误容错处理
- ✅ 性能优化（批量获取、缓存）

用户现在可以在账户卡片中直观地看到每个账户使用的代理IP及其运行状况，便于监控和管理。
