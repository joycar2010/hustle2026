# 点差提醒未触发诊断总结

## 诊断时间
2026-03-09 00:21

## 核心发现

### ✓ 正常的部分

1. **后台服务运行正常**
   - 服务状态：健康
   - 端口：8000

2. **点差数据正常更新**
   - 最新数据：Forward: -2.64, Reverse: 2.37
   - 更新频率：每秒

3. **提醒模板配置正确**
   - 4个点差提醒模板全部激活
   - 飞书通知全部启用

4. **AccountBalanceStreamer已启动**
   - 代码位置：main.py:82
   - 启动事件：lifespan startup

### ❌ 问题所在

#### 1. admin用户反向开仓条件满足但未触发

**当前状态：**
- Reverse Spread: 2.37
- admin阈值: 2.0
- **✓ 满足触发条件** (2.37 >= 2.0)

**但是：**
- 最近1小时没有任何通知日志
- 最后一次点差通知：2026-03-06 09:35（3天前）

#### 2. 检查间隔配置未生效

**修改前：**
- broadcast_tasks.py: 硬编码10秒
- 实际运行：10秒检查一次

**修改后：**
- 已改为使用 settings.MARKET_DATA_UPDATE_INTERVAL (1秒)
- **需要重启后台服务才能生效**

#### 3. 冷却时间配置未生效

**修改前：**
- spread_alert_service.py: 硬编码60秒
- 实际冷却：60秒

**修改后：**
- 已改为使用 settings.SPREAD_ALERT_COOLDOWN (5秒)
- **需要重启后台服务才能生效**

## 未触发的可能原因

### 原因1：后台任务未实际执行检查

虽然AccountBalanceStreamer已启动，但可能：
- 检查逻辑中有异常被捕获
- 日志级别设置导致错误未显示
- 数据库连接问题

**验证方法：**
```bash
# 查看后台日志
tail -f backend/logs/app.log | grep -i "spread\|alert\|risk"
```

### 原因2：点差数据获取失败

在broadcast_tasks.py:300中：
```python
market_data = await market_data_service.get_current_spread()
```

如果这个调用失败，后续检查不会执行。

**验证方法：**
```bash
# 测试API
curl http://localhost:8000/api/v1/market/spread
```

### 原因3：用户风险设置未正确读取

在broadcast_tasks.py:303-308中读取risk_settings，可能：
- 查询失败
- 数据为None
- 字段名不匹配

### 原因4：异常被静默捕获

代码中有多个try-except块：
- broadcast_tasks.py:324: `except Exception as e: logger.error(...)`
- spread_alert_service.py:251: `except Exception as e: logger.error(...)`

错误可能被记录但未显示。

## 立即行动

### 1. 重启后台服务（应用新配置）

```bash
# 停止当前服务
ps aux | grep "python.*app.main" | grep -v grep | awk '{print $2}' | xargs kill

# 启动新服务
cd /c/app/hustle2026/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
```

### 2. 实时监控日志

```bash
# 监控所有相关日志
tail -f backend/logs/app.log | grep -E "spread|alert|risk|AccountBalance"
```

### 3. 测试点差API

```bash
# 测试市场数据服务
curl http://localhost:8000/api/v1/market/spread

# 测试风险设置
curl http://localhost:8000/api/v1/risk/settings
```

### 4. 手动触发测试

创建测试脚本直接调用检查逻辑：
```python
# test_spread_alert.py
import asyncio
from app.services.spread_alert_service import SpreadAlertService
from app.core.database import AsyncSessionLocal

async def test():
    service = SpreadAlertService()
    async with AsyncSessionLocal() as db:
        market_data = {
            'forward_spread': -2.64,
            'reverse_spread': 2.37
        }
        alert_settings = {
            'forwardOpenPrice': 3.0,
            'forwardClosePrice': 1.0,
            'reverseOpenPrice': 2.0,
            'reverseClosePrice': 1.0
        }
        await service.check_and_send_spread_alerts(
            db=db,
            user_id='0bc9c5f7-dc77-4f7d-bfbf-4b347a934b24',
            market_data=market_data,
            alert_settings=alert_settings
        )

asyncio.run(test())
```

## 预期结果

重启后台服务后：
1. 检查间隔从10秒变为1秒
2. 冷却时间从60秒变为5秒
3. admin用户应该立即收到反向开仓提醒（因为2.37 >= 2.0）
4. 每5秒可以重复提醒（如果条件持续满足）

## 验证清单

- [ ] 重启后台服务
- [ ] 确认新配置生效（日志显示interval: 1s）
- [ ] 监控日志中的点差检查记录
- [ ] 确认收到飞书通知
- [ ] 确认前端弹窗显示
- [ ] 检查notification_logs表有新记录
- [ ] 测试其他阈值条件

## 后续优化建议

1. **添加健康检查API**
   - 显示后台任务运行状态
   - 显示最后检查时间
   - 显示检查次数统计

2. **增强日志记录**
   - 记录每次检查的点差值
   - 记录触发条件判断结果
   - 记录发送通知的详细信息

3. **添加调试模式**
   - 可以临时降低阈值测试
   - 可以强制触发通知
   - 可以查看冷却状态

4. **监控告警**
   - 如果超过5分钟没有检查记录，发送告警
   - 如果通知发送失败率过高，发送告警
