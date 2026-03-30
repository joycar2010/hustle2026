# MT5 客户端状态功能优化方案

## 一、现状分析

### 1.1 Windows Agent 现状
- **位置**：`C:\MT5Agent\main.py`
- **功能**：基础实例管理（部署、启动、停止、重启、删除）
- **缺失**：健康检查、自动重启、批量操作、并发控制

### 1.2 前端显示现状

#### MasterDashboard.vue（总控面板）
- **路径**：`frontend/src-admin/views/MasterDashboard.vue`
- **数据源**：`/api/v1/monitor/status` → `mt5_clients` 数组
- **显示**：客户端名称、用户、MT5登录、服务器、连接状态
- **问题**：
  - ❌ 无实时刷新（依赖手动刷新）
  - ❌ 无进程健康状态
  - ❌ 无控制按钮

#### UserManagement.vue（用户管理）
- **路径**：`frontend/src-admin/views/UserManagement.vue`
- **数据源**：`/api/v1/accounts/{account_id}/mt5-clients`
- **显示**：完整 MT5 客户端卡片 + 实例列表 + 控制按钮
- **问题**：
  - ❌ 需手动选择用户/账户
  - ❌ 状态更新不够实时

### 1.3 后端 API 现状
- ✅ `/api/v1/mt5-clients/system-service/status` - 系统服务账户状态
- ✅ `/api/v1/mt5-server/status` - Windows Agent 服务器状态
- ✅ `/api/v1/accounts/{account_id}/mt5-clients` - 账户 MT5 客户端列表

---

## 二、优化方案（渐进式）

### 2.1 前端优化 - MasterDashboard.vue

#### 2.1.1 添加自动刷新机制
```javascript
// 在 onMounted 中添加定时器
let mt5StatusTimer = null

onMounted(() => {
  fetchMonitorStatus()
  fetchMT5Status()

  // 每 5 秒刷新 MT5 客户端状态
  mt5StatusTimer = setInterval(() => {
    fetchMonitorStatus()
  }, 5000)
})

onUnmounted(() => {
  if (mt5StatusTimer) clearInterval(mt5StatusTimer)
})
```

#### 2.1.2 增强状态显示
```vue
<!-- 添加进程健康指示器 -->
<div class="flex justify-between items-center">
  <span class="text-text-tertiary">进程状态:</span>
  <span class="px-1.5 py-0.5 rounded text-xs"
    :class="c.process_running ? 'bg-[#0ecb81]/10 text-[#0ecb81]' : 'bg-[#f6465d]/10 text-[#f6465d]'">
    {{ c.process_running ? '运行中' : '已停止' }}
  </span>
</div>

<!-- 添加最后心跳时间 -->
<div class="flex justify-between">
  <span class="text-text-tertiary">最后心跳:</span>
  <span class="text-text-secondary">{{ formatLastSeen(c.last_connected_at) }}</span>
</div>
```

#### 2.1.3 添加快速控制按钮
```vue
<!-- 在 MT5 客户端卡片底部添加 -->
<div class="flex gap-1.5 mt-2 pt-2 border-t border-border-secondary">
  <button @click="controlMT5Instance(c, 'restart')"
    class="flex-1 py-1 bg-[#3dccc7]/10 hover:bg-[#3dccc7]/20 text-[#3dccc7] rounded text-xs">
    重启
  </button>
  <button @click="viewDetails(c)"
    class="flex-1 py-1 bg-primary/10 hover:bg-primary/20 text-primary rounded text-xs">
    详情
  </button>
</div>
```

### 2.2 前端优化 - UserManagement.vue

#### 2.2.1 优化实例状态轮询
```javascript
// 当有实例操作进行时，提高轮询频率
let instanceStatusTimer = null

function startInstanceStatusPolling() {
  if (instanceStatusTimer) return

  instanceStatusTimer = setInterval(async () => {
    if (mt5SelectedAccountId.value) {
      await loadMT5Clients()
    }
  }, 3000) // 3秒轮询
}

function stopInstanceStatusPolling() {
  if (instanceStatusTimer) {
    clearInterval(instanceStatusTimer)
    instanceStatusTimer = null
  }
}

// 在实例操作时启动轮询
async function controlInstance(inst, action) {
  startInstanceStatusPolling()
  // ... 执行操作
  setTimeout(stopInstanceStatusPolling, 30000) // 30秒后停止
}
```

#### 2.2.2 添加批量操作
```vue
<!-- 添加批量控制按钮 -->
<div class="flex gap-2 mt-3">
  <button @click="batchControlInstances('start')"
    class="px-3 py-1.5 bg-[#0ecb81]/10 text-[#0ecb81] rounded-lg text-xs">
    批量启动
  </button>
  <button @click="batchControlInstances('stop')"
    class="px-3 py-1.5 bg-[#f0b90b]/10 text-[#f0b90b] rounded-lg text-xs">
    批量停止
  </button>
  <button @click="batchControlInstances('restart')"
    class="px-3 py-1.5 bg-[#3dccc7]/10 text-[#3dccc7] rounded-lg text-xs">
    批量重启
  </button>
</div>
```

### 2.3 后端优化

#### 2.3.1 增强 `/api/v1/monitor/status` 端点
```python
# backend/app/api/v1/monitor.py

@router.get("/monitor/status")
async def get_monitor_status(db: AsyncSession = Depends(get_db)):
    """获取系统监控状态（增强版）"""

    # 获取所有活跃的 MT5 客户端
    result = await db.execute(
        select(MT5Client)
        .where(MT5Client.is_active == True)
        .where(MT5Client.is_system_service == False)  # 排除系统服务账户
    )
    mt5_clients = result.scalars().all()

    # 获取每个客户端的实例状态
    client_data = []
    for client in mt5_clients:
        # 获取关联的实例
        instance_result = await db.execute(
            select(MT5Instance)
            .where(MT5Instance.client_id == client.client_id)
            .where(MT5Instance.is_active == True)
        )
        instance = instance_result.scalar_one_or_none()

        # 检查进程状态
        process_running = False
        if instance:
            try:
                # 调用 Windows Agent 检查进程
                agent = MT5AgentService(
                    server_ip=instance.server_ip,
                    agent_port=9000
                )
                health = await agent.check_instance_health(instance.instance_id)
                process_running = health.get("running", False)
            except:
                pass

        client_data.append({
            "client_id": str(client.client_id),
            "client_name": client.client_name,
            "mt5_login": str(client.mt5_login),
            "mt5_server": client.mt5_server,
            "connection_status": client.connection_status,
            "online": client.connection_status == "connected",
            "process_running": process_running,
            "last_connected_at": client.last_connected_at.isoformat() if client.last_connected_at else None,
            "username": client.account.user.username if client.account and client.account.user else None,
        })

    return {
        "mt5_clients": client_data,
        # ... 其他监控数据
    }
```

#### 2.3.2 添加 Windows Agent 健康检查端点
```python
# C:\MT5Agent\main.py

@app.get("/instances/{instance_id}/health")
async def check_instance_health(instance_id: str):
    """检查实例健康状态"""
    instances = load_instances()

    if instance_id not in instances:
        raise HTTPException(404, "Instance not found")

    inst = instances[instance_id]
    port = inst.get("service_port")

    # 检查端口是否被占用（进程是否运行）
    running = is_port_in_use(port)

    # 如果运行中，检查桥接服务健康
    mt5_connected = False
    if running:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://localhost:{port}/health")
                data = resp.json()
                mt5_connected = data.get("mt5", False)
        except:
            pass

    return {
        "instance_id": instance_id,
        "running": running,
        "mt5_connected": mt5_connected,
        "port": port,
        "timestamp": datetime.now().isoformat()
    }
```

### 2.4 数据一致性保障

#### 2.4.1 定期同步数据库状态
```python
# backend/app/services/mt5_sync_service.py

class MT5SyncService:
    """MT5 客户端状态同步服务"""

    async def sync_client_status(self, db: AsyncSession):
        """同步所有 MT5 客户端状态"""

        # 获取所有活跃客户端
        result = await db.execute(
            select(MT5Client).where(MT5Client.is_active == True)
        )
        clients = result.scalars().all()

        for client in clients:
            # 获取关联实例
            instance_result = await db.execute(
                select(MT5Instance)
                .where(MT5Instance.client_id == client.client_id)
                .where(MT5Instance.is_active == True)
            )
            instance = instance_result.scalar_one_or_none()

            if not instance:
                # 无实例，标记为未连接
                client.connection_status = "disconnected"
                continue

            # 检查桥接服务健康
            try:
                async with httpx.AsyncClient(timeout=2.0) as http_client:
                    resp = await http_client.get(
                        f"http://{instance.server_ip}:{instance.service_port}/health"
                    )
                    data = resp.json()

                    if data.get("mt5", False):
                        client.connection_status = "connected"
                        client.last_connected_at = datetime.now()
                    else:
                        client.connection_status = "disconnected"
            except:
                client.connection_status = "error"

        await db.commit()
```

#### 2.4.2 添加后台任务
```python
# backend/app/main.py

from app.services.mt5_sync_service import MT5SyncService
import asyncio

@app.on_event("startup")
async def startup_event():
    """启动后台同步任务"""

    async def sync_loop():
        while True:
            try:
                async with get_db_session() as db:
                    sync_service = MT5SyncService()
                    await sync_service.sync_client_status(db)
            except Exception as e:
                logger.error(f"MT5 sync error: {e}")

            await asyncio.sleep(10)  # 每 10 秒同步一次

    asyncio.create_task(sync_loop())
```

---

## 三、实施步骤

### 阶段 1：前端优化（1-2天）
1. ✅ MasterDashboard.vue 添加自动刷新
2. ✅ 增强状态显示（进程状态、最后心跳）
3. ✅ 添加快速控制按钮
4. ✅ UserManagement.vue 优化轮询机制

### 阶段 2：后端增强（2-3天）
1. ✅ 增强 `/api/v1/monitor/status` 端点
2. ✅ Windows Agent 添加健康检查端点
3. ✅ 实现 MT5SyncService 同步服务
4. ✅ 添加后台同步任务

### 阶段 3：测试验证（1天）
1. ✅ 测试自动刷新功能
2. ✅ 测试控制按钮（启动/停止/重启）
3. ✅ 测试数据一致性
4. ✅ 压力测试（多实例并发）

---

## 四、方案 B：部署完整 MT5InstanceManager（可选）

如果需要更高级的功能（健康检查、自动重启、批量操作），可以部署用户提供的完整 MT5InstanceManager 类。

### 优点
- ✅ 配置驱动的实例管理
- ✅ 健康检查和自动重启
- ✅ 批量操作和标签过滤
- ✅ ThreadPoolExecutor 并发控制

### 缺点
- ❌ 需要重构现有 Windows Agent
- ❌ 需要迁移现有实例配置
- ❌ 测试工作量大

### 建议
**暂不部署**，先完成方案 A 的渐进式优化。如果后续需要更高级功能，再考虑部署完整版本。

---

## 五、关键技术细节

### 5.1 实时状态更新策略
- **轮询间隔**：
  - 正常状态：10 秒
  - 操作进行中：3 秒
  - 错误状态：5 秒
- **超时设置**：HTTP 请求 2-3 秒超时
- **错误处理**：失败后降级显示，不阻塞 UI

### 5.2 进程状态判断
```python
def is_process_running(port: int) -> bool:
    """通过端口判断进程是否运行"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', port))
    sock.close()
    return result == 0
```

### 5.3 数据库状态同步
- **同步频率**：10 秒
- **同步内容**：connection_status, last_connected_at
- **异常处理**：失败不影响主服务

---

## 六、验证清单

- [ ] MasterDashboard 自动刷新 MT5 客户端状态
- [ ] 显示进程运行状态和最后心跳时间
- [ ] 快速控制按钮可用（重启、详情）
- [ ] UserManagement 实例状态实时更新
- [ ] 批量操作功能正常
- [ ] 数据库状态与实际进程状态一致
- [ ] Windows Agent 健康检查端点正常
- [ ] 后台同步任务稳定运行
- [ ] 错误处理和降级显示正常
- [ ] 多实例并发操作无冲突

---

## 七、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 频繁轮询导致性能问题 | 中 | 使用合理的轮询间隔，添加请求缓存 |
| 数据库状态不一致 | 高 | 后台同步任务 + 前端实时检查 |
| Windows Agent 单点故障 | 高 | 添加健康检查和自动重启机制 |
| 并发控制操作冲突 | 中 | 添加操作锁和状态检查 |

---

## 八、总结

**推荐方案**：方案 A（渐进式优化）

**理由**：
1. 风险可控，不影响现有功能
2. 实施周期短（4-6天）
3. 满足当前业务需求
4. 为未来升级预留空间

**不推荐**：立即部署完整 MT5InstanceManager

**理由**：
1. 重构工作量大
2. 测试周期长
3. 当前基础版本已满足核心需求
