# 通知系统关联关系文档

## 概述
本文档详细说明了风险控制提醒项、通知模板、前端弹窗提示和飞书通知系统之间的关联关系。

---

## 1. 风险控制提醒项 (Risk.vue)

### 1.1 净资产提醒
- **binanceNetAsset**: Binance净资产阈值
- **bybitMT5NetAsset**: Bybit MT5净资产阈值
- **totalNetAsset**: 总资产阈值

### 1.2 爆仓价位提醒
- **binanceLiquidationPrice**: Binance爆仓价格阈值
- **bybitMT5LiquidationPrice**: Bybit MT5爆仓价格阈值

### 1.3 MT5卡顿提醒
- **mt5LagCount**: MT5卡顿次数阈值

### 1.4 反向套利提醒 (Long Bybit)
- **reverseOpenPrice**: 反向开仓点差值阈值
- **reverseOpenSyncCount**: 反向开仓同步条数
- **reverseClosePrice**: 反向平仓点差值阈值
- **reverseCloseSyncCount**: 反向平仓同步条数

### 1.5 正向套利提醒 (Long Binance)
- **forwardOpenPrice**: 正向开仓点差值阈值
- **forwardOpenSyncCount**: 正向开仓同步条数
- **forwardClosePrice**: 正向平仓点差值阈值
- **forwardCloseSyncCount**: 正向平仓同步条数

---

## 2. 后端通知模板 (notification_templates)

### 2.1 点差值提醒模板
| Template Key | Template Name | Category | Priority | 对应风控项 |
|-------------|--------------|----------|----------|-----------|
| `forward_open_spread_alert` | 优惠价格提醒 | risk | 3 | forwardOpenPrice |
| `forward_close_spread_alert` | 价格回归提醒 | risk | 3 | forwardClosePrice |
| `reverse_open_spread_alert` | 反向优惠提醒 | risk | 3 | reverseOpenPrice |
| `reverse_close_spread_alert` | 反向价格回归 | risk | 3 | reverseClosePrice |

### 2.2 净资产提醒模板
| Template Key | Template Name | Category | Priority | 对应风控项 |
|-------------|--------------|----------|----------|-----------|
| `binance_net_asset_alert` | A仓库资产提醒 | risk | 3 | binanceNetAsset |
| `bybit_net_asset_alert` | B仓库资产提醒 | risk | 3 | bybitMT5NetAsset |

### 2.3 爆仓价提醒模板
| Template Key | Template Name | Category | Priority | 对应风控项 |
|-------------|--------------|----------|----------|-----------|
| `binance_liquidation_alert` | A仓库安全线提醒 | risk | 4 | binanceLiquidationPrice |
| `bybit_liquidation_alert` | B仓库安全线提醒 | risk | 4 | bybitMT5LiquidationPrice |

### 2.4 MT5提醒模板
| Template Key | Template Name | Category | Priority | 对应风控项 |
|-------------|--------------|----------|----------|-----------|
| `mt5_lag_alert` | 配送系统延迟 | risk | 4 | mt5LagCount |

### 2.5 单腿提醒模板
| Template Key | Template Name | Category | Priority | 对应风控项 |
|-------------|--------------|----------|----------|-----------|
| `single_leg_alert` | 单边配送提醒 | risk | 4 | (动态触发) |

---

## 3. 前端弹窗提示 (notification.js)

### 3.1 Alert Type 映射

| Frontend Alert Type | 触发函数 | 对应后端Template Key | Level |
|-------------------|---------|---------------------|-------|
| `forward_open` | checkMarketAlerts() | forward_open_spread_alert | warning |
| `forward_close` | checkMarketAlerts() | forward_close_spread_alert | info |
| `reverse_open` | checkMarketAlerts() | reverse_open_spread_alert | warning |
| `reverse_close` | checkMarketAlerts() | reverse_close_spread_alert | info |
| `binance_asset` | checkAccountAlerts() | binance_net_asset_alert | critical |
| `bybit_asset` | checkAccountAlerts() | bybit_net_asset_alert | critical |
| `total_asset` | checkAccountAlerts() | (无对应模板) | critical |
| `mt5_lag` | checkMT5LagAlert() | mt5_lag_alert | warning |
| `single_leg_alert` | checkSingleLegAlert() | single_leg_alert | critical |

### 3.2 音频提醒映射

| Alert Type Category | Sound Setting | Repeat Count Setting |
|--------------------|--------------|---------------------|
| single_leg | singleLegAlertSound | singleLegAlertRepeatCount |
| forward/reverse spread | spreadAlertSound | spreadAlertRepeatCount |
| asset alerts | netAssetAlertSound | netAssetAlertRepeatCount |
| mt5 alerts | mt5AlertSound | mt5AlertRepeatCount |
| liquidation alerts | liquidationAlertSound | liquidationAlertRepeatCount |

---

## 4. 飞书通知系统

### 4.1 通知发送流程

```
风险监控服务 (RiskMetricsStreamer/SpreadAlertService)
    ↓
检查阈值条件
    ↓
获取通知模板 (NotificationTemplate)
    ↓
渲染模板变量
    ↓
发送飞书卡片消息 (FeishuService.send_card_message)
    ↓
~~发送飞书音频消息 (已移除)~~
    ↓
记录通知日志 (NotificationLog)
    ↓
WebSocket广播到前端 (manager.send_personal_message)
```

### 4.2 飞书通知配置

- **App ID**: cli_a9235819f078dcbd
- **接收方式**: email (用户邮箱)
- **消息类型**: 卡片消息 (Card Message)
- **颜色映射**:
  - Priority 1-2: blue
  - Priority 3: orange
  - Priority 4: red

### 4.3 音频提醒状态

**已移除**: 飞书卡片消息的音频提醒功能已在 2026-03-07 移除
- spread_alert_service.py: 音频发送代码仍存在 (lines 221-250)
- risk_alert_service.py: 音频发送代码已注释 (lines 162-190)

---

## 5. 完整关联流程图

### 5.1 点差值提醒流程

```
用户设置 forwardOpenPrice = 10 USDT (Risk.vue)
    ↓
RiskMetricsStreamer 监控市场数据
    ↓
forward_spread >= 10 USDT
    ↓
SpreadAlertService.check_and_send_spread_alerts()
    ↓
查询模板: forward_open_spread_alert
    ↓
渲染变量: {spread, threshold, market_status, estimated_profit}
    ↓
发送飞书卡片: "💰 优惠价格机会提醒"
    ↓
WebSocket广播: alert_type = "forward_open"
    ↓
前端 notification.js 接收
    ↓
checkMarketAlerts() 触发弹窗
    ↓
播放音频: spreadAlertSound (重复 spreadAlertRepeatCount 次)
```

### 5.2 净资产提醒流程

```
用户设置 binanceNetAsset = 1000 USDT (Risk.vue)
    ↓
RiskMetricsStreamer 监控账户数据
    ↓
binance_net_asset <= 1000 USDT
    ↓
RiskAlertService.send_risk_alert()
    ↓
查询模板: binance_net_asset_alert
    ↓
渲染变量: {current_asset, threshold, status}
    ↓
发送飞书卡片: "💰 A仓库资产预警"
    ↓
WebSocket广播: alert_type = "binance_asset"
    ↓
前端 notification.js 接收
    ↓
checkAccountAlerts() 触发弹窗
    ↓
播放音频: netAssetAlertSound (重复 netAssetAlertRepeatCount 次)
```

### 5.3 MT5卡顿提醒流程

```
用户设置 mt5LagCount = 5 (Risk.vue)
    ↓
RiskMetricsStreamer 监控MT5连接状态
    ↓
lag_count >= 5
    ↓
RiskAlertService.send_risk_alert()
    ↓
查询模板: mt5_lag_alert
    ↓
渲染变量: {failure_count, last_response_time}
    ↓
发送飞书卡片: "⚠️ 配送系统延迟提醒"
    ↓
WebSocket广播: alert_type = "mt5_lag"
    ↓
前端 notification.js 接收
    ↓
checkMT5LagAlert() 触发弹窗
    ↓
播放音频: mt5AlertSound (重复 mt5AlertRepeatCount 次)
```

---

## 6. 缺失映射和注意事项

### 6.1 缺失的后端模板

以下风控项**没有对应的后端通知模板**:
- `totalNetAsset` (总资产提醒)
  - 前端有检查逻辑 (notification.js:138-148)
  - 后端无对应模板
  - 建议: 添加 `total_net_asset_alert` 模板

### 6.2 未实现的前端检查

以下后端模板**没有对应的前端检查逻辑**:
- `binance_liquidation_alert` (Binance爆仓价提醒)
- `bybit_liquidation_alert` (Bybit爆仓价提醒)
  - 后端有模板定义
  - 前端 notification.js 有音频映射 (line 236-239)
  - 但缺少检查函数 (如 checkLiquidationAlerts)
  - 建议: 添加爆仓价检查逻辑

### 6.3 同步条数设置

以下设置项**未在通知系统中使用**:
- `forwardOpenSyncCount`
- `forwardCloseSyncCount`
- `reverseOpenSyncCount`
- `reverseCloseSyncCount`

这些可能用于其他业务逻辑,不属于通知系统范畴。

### 6.4 音频提醒一致性

- **前端音频**: 完全保留,用户可配置
- **飞书音频**:
  - risk_alert_service.py: 已注释移除
  - spread_alert_service.py: 代码仍存在但未使用

建议: 统一移除 spread_alert_service.py 中的音频发送代码 (lines 221-250)

---

## 7. 系统架构总结

### 7.1 数据流向

```
风险控制设置 (Risk.vue)
    ↓
后端监控服务 (RiskMetricsStreamer)
    ↓
触发条件检查
    ↓
通知模板系统 (NotificationTemplate)
    ↓
飞书通知 (FeishuService) + WebSocket广播
    ↓
前端通知存储 (notification.js)
    ↓
弹窗提示 + 音频播放
```

### 7.2 关键服务

| 服务 | 文件路径 | 职责 |
|-----|---------|-----|
| RiskMetricsStreamer | backend/app/services/risk_alert_service.py | 监控风险指标,触发提醒 |
| SpreadAlertService | backend/app/services/spread_alert_service.py | 监控点差值,发送提醒 |
| FeishuService | backend/app/services/feishu_service.py | 发送飞书消息 |
| NotificationStore | frontend/src/stores/notification.js | 前端通知管理 |
| WebSocket Manager | backend/app/websocket/manager.py | 实时消息推送 |

### 7.3 数据库表

| 表名 | 用途 |
|-----|-----|
| notification_configs | 通知服务配置 (飞书/邮件/短信) |
| notification_templates | 通知模板定义 |
| notification_logs | 通知发送日志 |
| user_notification_settings | 用户通知偏好 |

---

## 8. 维护建议

1. **补充缺失模板**: 为 `totalNetAsset` 添加后端通知模板
2. **实现爆仓价检查**: 在前端添加 `checkLiquidationAlerts()` 函数
3. **清理冗余代码**: 移除 spread_alert_service.py 中未使用的音频发送代码
4. **统一命名规范**: 确保前后端 alert_type 命名一致
5. **文档同步更新**: 当添加新的提醒项时,同步更新本文档

---

**文档版本**: 1.0
**最后更新**: 2026-03-07
**维护人员**: Claude Sonnet 4.6
