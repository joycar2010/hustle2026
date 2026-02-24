# WebSocket问题排查快速参考指南

**适用对象：** 开发团队、运维团队
**版本：** 1.0.0
**最后更新：** 2026-02-24

---

## 🚨 快速诊断流程

### 步骤1：检查WebSocket服务是否运行

```bash
# 检查后端进程
ps aux | grep uvicorn

# 应该看到类似输出：
# uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**✅ 正常：** 看到uvicorn进程运行中
**❌ 异常：** 没有进程 → 启动后端服务

---

### 步骤2：测试WebSocket连接

```bash
# 使用验证脚本
cd c:/app/hustle2026
python scripts/test_websocket.py --url ws://13.115.21.77:8000/ws --timeout 10
```

**✅ 正常：** 显示"WebSocket连接成功"并收到消息
**❌ 异常：** 连接失败 → 查看错误信息

---

### 步骤3：检查前端WebSocket状态

**浏览器控制台：**
```javascript
// 打开 http://13.115.21.77:3000
// 按F12打开开发者工具
// 在Console中输入：

// 检查market store状态
const marketStore = useMarketStore()
console.log('WebSocket连接状态:', marketStore.connected)
console.log('最新市场数据:', marketStore.marketData)
```

**Network标签：**
```
1. 打开Network标签
2. 筛选WS (WebSocket)
3. 查找 ws://13.115.21.77:8000/ws
4. 检查Status: 应该是 "101 Switching Protocols"
```

---

### 步骤4：检查System页面配置

```
1. 访问 http://13.115.21.77:3000/system
2. 切换到"刷新管理"标签页
3. 检查"使用WebSocket"开关是否开启
4. 查看"WebSocket状态"显示
```

**✅ 正常：** 开关开启，状态显示"已连接"
**❌ 异常：** 状态显示"未连接" → 点击开关并保存

---

## 🔍 常见问题排查

### 问题1：WebSocket状态显示"未连接"

**可能原因：**
1. WebSocket开关未开启
2. 后端服务未启动
3. 网络连接问题
4. Token鉴权失败

**排查步骤：**

```bash
# 1. 检查后端服务
ps aux | grep uvicorn

# 2. 检查端口监听
netstat -an | grep 8000

# 3. 测试连接
python scripts/test_websocket.py

# 4. 检查日志
tail -f /tmp/backend.log
```

**解决方案：**
```javascript
// 前端手动连接
import { useMarketStore } from '@/stores/market'
const marketStore = useMarketStore()
marketStore.connect()
```

---

### 问题2：WebSocket连接后立即断开

**可能原因：**
1. Token无效或过期
2. 鉴权失败
3. 服务器主动断开

**排查步骤：**

```bash
# 查看后端日志
tail -f /tmp/backend.log | grep WebSocket

# 使用有效Token测试
python scripts/test_websocket.py --token "your_token_here"
```

**解决方案：**
```javascript
// 刷新Token
localStorage.removeItem('token')
// 重新登录获取新Token
```

---

### 问题3：收不到WebSocket消息

**可能原因：**
1. 后端推送服务未启动
2. 没有可推送的数据
3. 消息类型不匹配

**排查步骤：**

```bash
# 检查后端推送服务
python scripts/test_websocket.py --timeout 30

# 查看后端日志
tail -f /tmp/backend.log | grep "broadcast"
```

**解决方案：**
```python
# 检查后端推送服务是否启动
# backend/app/main.py
# 确保以下服务已启动：
# - Binance WebSocket客户端
# - 市场数据流服务
# - 持仓监控服务
```

---

### 问题4：轮询和WebSocket同时运行

**可能原因：**
1. 组件未改造完成
2. 轮询代码未移除

**排查步骤：**

```bash
# 运行轮询检测脚本
python scripts/detect_polling.py --project-root frontend/src --output report.md

# 查看报告
cat report.md
```

**解决方案：**
```javascript
// 移除轮询代码
// ❌ 删除
// const timer = setInterval(fetchData, 1000)

// ✅ 使用WebSocket
import { useMarketStore } from '@/stores/market'
const marketStore = useMarketStore()

watch(() => marketStore.marketData, (newData) => {
  // 处理新数据
})
```

---

## 📋 验证清单

### WebSocket连接验证

- [ ] 后端uvicorn进程运行中
- [ ] 端口8000正常监听
- [ ] WebSocket连接测试通过
- [ ] 能够收到推送消息
- [ ] 前端market store状态为connected
- [ ] System页面显示"已连接"

### 配置验证

- [ ] System页面WebSocket开关已开启
- [ ] localStorage中保存了配置
- [ ] 配置变更后连接状态正确切换
- [ ] 页面刷新后配置保持

### 功能验证

- [ ] 市场数据实时更新
- [ ] 风险警报正常推送
- [ ] 订单更新正常推送
- [ ] 断线后自动重连
- [ ] 无轮询残留

---

## 🛠️ 常用命令

### 后端操作

```bash
# 启动后端
cd c:/app/hustle2026/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 查看日志
tail -f /tmp/backend.log

# 重启后端
ps aux | grep uvicorn | awk '{print $2}' | xargs kill -9
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
```

### 前端操作

```bash
# 启动前端
cd c:/app/hustle2026/frontend
npm run dev

# 清除缓存
rm -rf node_modules/.vite
npm run dev
```

### 测试操作

```bash
# WebSocket连接测试
python scripts/test_websocket.py

# 轮询检测
python scripts/detect_polling.py --project-root frontend/src --output report.md

# 查看报告
cat report.md
```

---

## 📞 技术支持

**遇到问题？**
- 查阅完整文档：[WEBSOCKET_DIAGNOSIS_REPORT.md](WEBSOCKET_DIAGNOSIS_REPORT.md)
- 查看审计报告：由Explore Agent生成
- 查看轮询检测报告：POLLING_DETECTION_REPORT.md
- 联系系统架构组

---

## 🔗 相关文档

- [WebSocket问题诊断报告](WEBSOCKET_DIAGNOSIS_REPORT.md)
- [轮询残留检测报告](POLLING_DETECTION_REPORT.md)
- [WebSocket连接测试脚本](scripts/test_websocket.py)
- [轮询检测脚本](scripts/detect_polling.py)

---

**记住：WebSocket连接问题90%是配置或状态同步问题，按照本指南逐步排查即可解决！**

**版本历史：**
- v1.0.0 (2026-02-24) - 初始版本
