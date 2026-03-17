# 多MT5账户客户端功能实施方案

## 实施日期
2026-03-16

## 功能概述
扩展系统以支持多个MT5账户客户端，每个Bybit账户可以关联一个MT5账户，实现多MT5账户的独立监控和管理。

## 当前架构分析

### 现有MT5支持
当前系统已经在Account模型中支持MT5账户：
```python
class Account:
    mt5_id = Column(String(100))           # MT5账户ID
    mt5_server = Column(String(100))       # MT5服务器地址
    mt5_primary_pwd = Column(String(256))  # MT5主密码
    is_mt5_account = Column(Boolean)       # 是否为MT5账户
```

### 现有问题
1. **单一MT5监控**: MarketCards.vue中只监控一个MT5连接
2. **缺少MT5客户端管理**: 没有专门的MT5客户端管理界面
3. **账户关联不明确**: MT5账户与Bybit账户的关联关系不够清晰

## 实施方案

### 方案A：基于现有Account模型（推荐）

#### 优点
- 无需修改数据库结构
- 利用现有的账户管理功能
- 实施成本低，风险小

#### 实施步骤

##### 1. 数据库层面
**无需修改**，当前Account模型已经支持：
- 一个账户可以是MT5账户（`is_mt5_account=True`）
- 存储MT5连接信息（`mt5_id`, `mt5_server`, `mt5_primary_pwd`）

##### 2. 后端API增强

**新增API端点**：
```python
# backend/app/api/v1/accounts.py

@router.get("/accounts/mt5/list")
async def get_mt5_accounts():
    """获取所有MT5账户列表"""
    # 返回所有 is_mt5_account=True 的账户
    pass

@router.get("/accounts/{account_id}/mt5/status")
async def get_mt5_connection_status(account_id: UUID):
    """获取MT5账户连接状态"""
    # 检查MT5客户端连接状态
    pass

@router.post("/accounts/{account_id}/mt5/connect")
async def connect_mt5_account(account_id: UUID):
    """连接MT5账户"""
    pass

@router.post("/accounts/{account_id}/mt5/disconnect")
async def disconnect_mt5_account(account_id: UUID):
    """断开MT5账户连接"""
    pass
```

##### 3. 前端账户卡片增强

**在 `/accounts` 页面的账户卡片中**：

```vue
<!-- 对于MT5账户，显示额外信息 -->
<div v-if="account.is_mt5_account" class="mt-2 space-y-1">
  <div class="flex items-center space-x-2 text-xs">
    <div class="w-2 h-2 rounded-full" :class="getMT5StatusColor(account)"></div>
    <span class="text-gray-400">MT5客户端:</span>
    <span :class="getMT5StatusTextColor(account)">
      {{ getMT5StatusText(account) }}
    </span>
  </div>
  <div class="text-xs text-gray-400">
    MT5 ID: {{ account.mt5_id }}
  </div>
  <div class="text-xs text-gray-400">
    服务器: {{ account.mt5_server }}
  </div>
</div>
```

##### 4. MarketCards.vue监控升级

**当前**：
```javascript
const bybitConnected = ref(false)  // 单一MT5连接状态
```

**升级为**：
```javascript
const mt5Connections = ref({})  // { account_id: { connected, account_name, ... } }
const mt5ConnectionsCount = computed(() => {
  const total = Object.keys(mt5Connections.value).length
  const connected = Object.values(mt5Connections.value).filter(c => c.connected).length
  return { total, connected }
})
```

**跑马灯显示**：
```
MT5: 3/5连接  // 表示5个MT5账户中有3个已连接
```

##### 5. SystemStatusModal增强

在系统状态模态框中添加MT5客户端详情：

```vue
<!-- MT5 Clients -->
<div class="bg-dark-200 rounded-lg p-4">
  <h3 class="font-medium mb-3">MT5客户端</h3>
  <div class="space-y-2">
    <div v-for="mt5 in mt5Connections" :key="mt5.account_id"
         class="flex items-center justify-between">
      <span class="text-sm text-text-tertiary">{{ mt5.account_name }}</span>
      <div class="flex items-center space-x-2">
        <div :class="['w-2 h-2 rounded-full', mt5.connected ? 'bg-success' : 'bg-danger']"></div>
        <span :class="['text-sm', mt5.connected ? 'text-success' : 'text-danger']">
          {{ mt5.connected ? '已连接' : '未连接' }}
        </span>
      </div>
    </div>
  </div>
</div>
```

### 方案B：独立MT5客户端管理表（备选）

#### 数据库设计
```sql
CREATE TABLE mt5_clients (
    client_id SERIAL PRIMARY KEY,
    account_id UUID REFERENCES accounts(account_id),
    client_name VARCHAR(100),
    mt5_account_id VARCHAR(100),
    mt5_server VARCHAR(100),
    mt5_password VARCHAR(256),
    connection_status VARCHAR(20),
    last_connected_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 优点
- MT5客户端信息独立管理
- 一个账户可以关联多个MT5客户端
- 更灵活的扩展性

#### 缺点
- 需要数据库迁移
- 需要更多的开发工作
- 增加系统复杂度

## 是否需要在/system中添加MT5管理模块？

### 建议：**不需要单独的MT5管理模块**

#### 理由

1. **功能重复**
   - 账户管理页面（`/accounts`）已经可以管理MT5账户
   - 添加单独模块会造成功能分散

2. **用户体验**
   - 用户在账户管理页面可以一站式管理所有账户（包括MT5）
   - 不需要在多个页面之间切换

3. **维护成本**
   - 单独模块需要额外的维护工作
   - 可能导致数据不一致

### 替代方案：增强现有功能

#### 在 `/accounts` 页面添加筛选功能
```vue
<div class="flex gap-2 mb-4">
  <button @click="filterType = 'all'"
          :class="filterType === 'all' ? 'btn-primary' : 'btn-secondary'">
    全部账户
  </button>
  <button @click="filterType = 'binance'"
          :class="filterType === 'binance' ? 'btn-primary' : 'btn-secondary'">
    Binance账户
  </button>
  <button @click="filterType = 'mt5'"
          :class="filterType === 'mt5' ? 'btn-primary' : 'btn-secondary'">
    MT5账户
  </button>
</div>
```

#### 在系统状态监控中显示MT5统计
- 跑马灯显示MT5连接数
- 系统状态模态框显示每个MT5客户端的详细状态

## 实施优先级

### 阶段1：基础功能（高优先级）
1. ✅ 修复System.vue标签页显示问题
2. 🔲 后端API：获取MT5账户列表
3. 🔲 后端API：获取MT5连接状态
4. 🔲 前端：账户卡片显示MT5状态
5. 🔲 前端：MarketCards.vue多MT5监控

### 阶段2：增强功能（中优先级）
1. 🔲 MT5客户端连接/断开控制
2. 🔲 MT5连接健康检查
3. 🔲 MT5连接告警
4. 🔲 账户页面MT5筛选功能

### 阶段3：高级功能（低优先级）
1. 🔲 MT5客户端性能监控
2. 🔲 MT5连接日志
3. 🔲 MT5客户端批量操作

## 技术实现细节

### 1. MT5连接状态管理

#### 后端服务
```python
# backend/app/services/mt5_connection_manager.py

class MT5ConnectionManager:
    def __init__(self):
        self.connections = {}  # { account_id: connection_info }

    async def get_connection_status(self, account_id: UUID) -> dict:
        """获取MT5连接状态"""
        return {
            "account_id": account_id,
            "connected": self.is_connected(account_id),
            "last_ping": self.get_last_ping(account_id),
            "latency_ms": self.get_latency(account_id)
        }

    async def get_all_connections(self) -> list:
        """获取所有MT5连接状态"""
        return [
            await self.get_connection_status(account_id)
            for account_id in self.connections.keys()
        ]
```

#### 前端Store
```javascript
// frontend/src/stores/mt5.js

export const useMT5Store = defineStore('mt5', {
  state: () => ({
    connections: {},  // { account_id: connection_info }
    loading: false
  }),

  getters: {
    connectedCount: (state) => {
      return Object.values(state.connections)
        .filter(c => c.connected).length
    },
    totalCount: (state) => {
      return Object.keys(state.connections).length
    }
  },

  actions: {
    async fetchConnections() {
      const response = await api.get('/api/v1/accounts/mt5/list')
      this.connections = response.data.reduce((acc, mt5) => {
        acc[mt5.account_id] = mt5
        return acc
      }, {})
    }
  }
})
```

### 2. WebSocket推送

#### 后端推送MT5状态变化
```python
# 当MT5连接状态变化时推送
await websocket_manager.broadcast({
    "type": "mt5_status",
    "data": {
        "account_id": account_id,
        "connected": connected,
        "timestamp": datetime.now().isoformat()
    }
})
```

#### 前端监听
```javascript
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'mt5_status') {
    mt5Store.updateConnection(message.data)
  }
})
```

### 3. 跑马灯显示逻辑

```javascript
// MarketCards.vue

const systemStatusText = computed(() => {
  const statuses = []

  // ... 其他状态

  // MT5连接状态
  if (mt5ConnectionsCount.value.total > 0) {
    const { connected, total } = mt5ConnectionsCount.value
    if (connected === total) {
      statuses.push(`MT5:${total}个全连接`)
    } else if (connected === 0) {
      statuses.push(`⚠️MT5:全部断开(${total}个)`)
    } else {
      statuses.push(`MT5:${connected}/${total}连接`)
    }
  }

  return statuses.join(' | ')
})
```

## 文件修改清单

### 已修改
1. ✅ `frontend/src/views/System.vue` - 修复标签页显示问题

### 需要创建
1. `backend/app/services/mt5_connection_manager.py` - MT5连接管理服务
2. `frontend/src/stores/mt5.js` - MT5状态管理Store

### 需要修改
1. `backend/app/api/v1/accounts.py` - 添加MT5相关API
2. `frontend/src/views/Accounts.vue` - 账户卡片显示MT5状态
3. `frontend/src/components/trading/MarketCards.vue` - 多MT5监控
4. `frontend/src/components/SystemStatusModal.vue` - MT5详情显示
5. `frontend/src/components/trading/AccountStatusPanel.vue` - 左侧栏MT5状态

## 测试计划

### 单元测试
1. MT5连接状态获取
2. MT5连接/断开操作
3. MT5状态推送

### 集成测试
1. 多个MT5账户同时连接
2. MT5连接状态实时更新
3. 跑马灯正确显示MT5状态

### 端到端测试
1. 创建MT5账户
2. 查看MT5状态
3. 连接/断开MT5
4. 监控MT5健康状态

## 风险评估

### 技术风险
- **低**: 基于现有架构扩展，风险可控
- MT5连接管理需要确保线程安全
- WebSocket推送需要处理连接断开重连

### 性能风险
- **低**: MT5状态查询频率需要控制
- 建议每30秒刷新一次状态
- 使用缓存减少数据库查询

### 兼容性风险
- **低**: 不影响现有功能
- 向后兼容，现有单MT5账户继续工作

## 总结

### 推荐方案
采用**方案A**（基于现有Account模型），理由：
1. 无需数据库迁移
2. 实施成本低
3. 利用现有功能
4. 风险可控

### 关于MT5管理模块
**不建议**在 `/system` 中添加单独的MT5管理模块，理由：
1. 功能重复
2. 增加维护成本
3. 用户体验不佳

### 替代方案
1. 在 `/accounts` 页面增强MT5账户管理
2. 在系统状态监控中显示MT5统计
3. 在跑马灯中显示MT5连接状态

### 下一步行动
1. ✅ 修复System.vue显示问题（已完成）
2. 实施后端MT5状态API
3. 实施前端MT5监控
4. 测试和优化

## 附录：System.vue显示问题修复

### 问题
标签页文字错位，可能是因为标签过多导致换行。

### 解决方案
```vue
<!-- 修改前 -->
<div class="flex space-x-2 mb-6 border-b border-border-primary">
  <button>...</button>
</div>

<!-- 修改后 -->
<div class="flex flex-wrap gap-2 mb-6 border-b border-border-primary pb-2">
  <button class="... whitespace-nowrap">...</button>
</div>
```

### 改进点
1. `flex-wrap`: 允许标签换行
2. `gap-2`: 使用gap替代space-x，支持换行后的间距
3. `pb-2`: 添加底部内边距，避免下划线与标签重叠
4. `whitespace-nowrap`: 防止标签文字内部换行
