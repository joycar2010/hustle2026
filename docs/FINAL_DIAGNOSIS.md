# 点差提醒未触发问题 - 最终诊断报告

## 时间
2026-03-09 00:28

## 已完成的修复

### 1. ✅ 检查间隔修改
- **修改前**: 10秒
- **修改后**: 1秒 (使用settings.MARKET_DATA_UPDATE_INTERVAL)
- **文件**: broadcast_tasks.py:26
- **状态**: 已应用并重启

### 2. ✅ 冷却时间修改
- **修改前**: 60秒
- **修改后**: 5秒 (使用settings.SPREAD_ALERT_COOLDOWN)
- **文件**: spread_alert_service.py:128
- **状态**: 已应用并重启

### 3. ✅ 点差字段名修复
- **问题**: 使用了错误的属性名 `forward_spread` 和 `reverse_spread`
- **正确**: 应该使用 `forward_entry_spread` 和 `reverse_entry_spread`
- **文件**: broadcast_tasks.py:313-314
- **状态**: 已修复并重启

## 当前状态

### 点差数据
- Forward Spread: -4.48
- Reverse Spread: 4.29

### 触发条件（admin用户）
- ✓ 正向开仓: 4.48 >= 3.0 (满足)
- ✓ 反向开仓: 4.29 >= 2.0 (满足)

### 通知状态
- ❌ 最近3分钟没有新的通知日志
- ❌ 点差提醒未触发

## 根本原因分析

经过深入检查，发现 `_check_risk_alerts` 函数可能根本没有被调用。让我检查调用链：

### 调用链
```
AccountBalanceStreamer._stream_loop()
  ↓
_check_risk_alerts(db, active_accounts, aggregated_data)
  ↓
SpreadAlertService.check_and_send_spread_alerts()
```

### 可能的问题

#### 1. _stream_loop 中的异常
如果 `_stream_loop` 中在调用 `_check_risk_alerts` 之前就抛出异常，后续代码不会执行。

#### 2. active_accounts 为空
如果没有激活的账户，`_check_risk_alerts` 可能不会执行点差检查。

#### 3. 飞书服务未初始化
从启动日志看到：
```
Initializing Feishu service from database...
Querying Feishu configuration...
Query result: config_found=True
```

但没有看到 "Feishu service initialized successfully" 的日志。

## 需要检查的代码位置

### broadcast_tasks.py 中的 _stream_loop

需要查看：
1. 第173行附近：`await self._check_risk_alerts(db, active_accounts, aggregated_data)`
2. 这行代码是否被执行
3. 是否有try-except捕获了异常

### broadcast_tasks.py 中的 _check_risk_alerts

需要查看：
1. 函数入口是否被调用
2. 是否有条件判断导致提前返回
3. 点差检查代码（298-324行）是否被执行

## 建议的调试步骤

### 1. 添加日志
在关键位置添加日志输出：

```python
# broadcast_tasks.py:173
logger.info(f"Calling _check_risk_alerts with {len(active_accounts)} accounts")
await self._check_risk_alerts(db, active_accounts, aggregated_data)

# broadcast_tasks.py:298
logger.info("Starting spread alert check")

# broadcast_tasks.py:301
market_data = await market_data_service.get_current_spread()
logger.info(f"Got market data: forward={market_data.forward_entry_spread}, reverse={market_data.reverse_entry_spread}")

# broadcast_tasks.py:319
logger.info(f"Calling spread alert service for user {user_id}")
await spread_alert_service.check_and_send_spread_alerts(...)
```

### 2. 检查飞书服务
```python
# 在 spread_alert_service.py:189
feishu = get_feishu_service()
logger.info(f"Feishu service: {feishu is not None}")
if not feishu:
    logger.warning("飞书服务未初始化")
    return
```

### 3. 手动测试
创建测试脚本直接调用 `_check_risk_alerts` 函数。

## 下一步行动

1. **立即**: 查看后台日志，搜索 "spread" 或 "alert" 关键词
2. **添加日志**: 在关键位置添加详细日志
3. **重启服务**: 应用日志修改后重启
4. **实时监控**: 使用 `tail -f` 监控日志输出
5. **手动测试**: 如果自动触发失败，手动调用测试

## 临时解决方案

如果自动触发一直失败，可以：
1. 创建一个API端点手动触发点差检查
2. 使用定时任务（cron）定期调用检查函数
3. 添加健康检查端点显示后台任务状态

## 文件清单

已修改的文件：
- [x] backend/app/tasks/broadcast_tasks.py (3处修改)
- [x] backend/app/services/spread_alert_service.py (2处修改)
- [x] backend/app/core/config.py (1处添加)

诊断脚本：
- backend/diagnose_spread_alerts.py
- backend/check_backend_tasks.py
- backend/test_spread_alert_manual.py
- backend/spread_alert_diagnosis_summary.md
- backend/spread_alert_verification.md
- backend/spread_alert_logic_analysis.md
