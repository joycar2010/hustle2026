# 提醒消息规则更新完成（带实时数据）

## 更新时间
2026-03-13

## 更新内容

已将所有提醒消息更新为简洁格式，并包含实时数据，符合用户要求。

### 1. 点差提醒消息（带实时点差数据）

#### 反向开仓 (reverse_open_spread_alert)
- **触发条件**: 做多bybit开仓点差值 > 反开差
- **消息**: "反向已到货，请查收11111（当前点差：{spread}）"
- **弹窗显示**:
  ```
  反向已到货，请查收11111
  当前点差：{spread}
  ```
- **注意**: 同一价格不重复提醒（60秒冷却时间）

#### 反向平仓 (reverse_close_spread_alert)
- **触发条件**: 做多bybit平仓点差值 < 反平差
- **消息**: "反向需清货，请清货00000（当前点差：{spread}）"
- **弹窗显示**:
  ```
  反向需清货，请清货00000
  当前点差：{spread}
  ```
- **注意**: 同一价格不重复提醒（60秒冷却时间）

#### 正向开仓 (forward_open_spread_alert)
- **触发条件**: 做多binance开仓点差值 > 正开差
- **消息**: "正向已到货，请查收11111（当前点差：{spread}）"
- **弹窗显示**:
  ```
  正向已到货，请查收11111
  当前点差：{spread}
  ```
- **注意**: 同一价格不重复提醒（60秒冷却时间）

#### 正向平仓 (forward_close_spread_alert)
- **触发条件**: 做多binance平仓点差值 < 正平差
- **消息**: "正向需清货，请清货00000（当前点差：{spread}）"
- **弹窗显示**:
  ```
  正向需清货，请清货00000
  当前点差：{spread}
  ```
- **注意**: 同一价格不重复提醒（60秒冷却时间）

### 2. 净资产提醒消息（带实时资产数据）

#### Binance净资产 (binance_net_asset_alert)
- **触发条件**: binance保证金余额 < binance净资产阈值
- **消息**: "*****A仓库需处理*****（当前：{current_asset}，阈值：{threshold}）"
- **弹窗显示**:
  ```
  *****A仓库需处理*****
  当前资产：{current_asset}
  预警阈值：{threshold}
  ```

#### Bybit净资产 (bybit_net_asset_alert)
- **触发条件**: bybit保证金余额 < bybit净资产阈值
- **消息**: "*****B仓库需处理*****（当前：{current_asset}，阈值：{threshold}）"
- **弹窗显示**:
  ```
  *****B仓库需处理*****
  当前资产：{current_asset}
  预警阈值：{threshold}
  ```

#### 总资产 (total_net_asset_alert)
- **触发条件**: 账户总资产 < 总资产阈值
- **消息**: "*****紧急紧急货不足*****（当前：{current_asset}，阈值：{threshold}）"
- **弹窗显示**:
  ```
  *****紧急紧急货不足*****
  当前总资产：{current_asset}
  预警阈值：{threshold}
  ```
- **优先级**: 4（红色，最高优先级）

### 3. 单腿提醒消息（带实时成交数据）

#### 单腿提醒 (single_leg_alert)
- **触发条件**: 检测到单腿交易（Binance成交但Bybit未成交或部分成交）
- **消息**: "B队员已瘸腿B（Binance：{binance_filled}，Bybit：{bybit_filled}）"
- **弹窗显示**:
  ```
  B队员已瘸腿B
  Binance成交：{binance_filled}
  Bybit成交：{bybit_filled}
  未成交量：{unfilled_qty}
  ```
- **优先级**: 4（红色，最高优先级）

## 实时数据变量说明

### 点差提醒变量
- `{spread}`: 当前实时点差值（USDT）

### 净资产提醒变量
- `{current_asset}`: 当前实时资产（USDT）
- `{threshold}`: 用户设置的预警阈值（USDT）

### 单腿提醒变量
- `{binance_filled}`: Binance实际成交量（XAU）
- `{bybit_filled}`: Bybit实际成交量（Lot）
- `{unfilled_qty}`: 未成交量（XAU）

## 配置说明

### 点差阈值配置
- **反开差**: 如果不填，不发送反向开仓提醒
- **反平差**: 如果不填，不发送反向平仓提醒
- **正开差**: 如果不填，不发送正向开仓提醒
- **正平差**: 如果不填，不发送正向平仓提醒

### 同一价格不重复提醒
系统已实现冷却时间机制（默认60秒），确保同一价格不会重复发送提醒。

## 技术实现

### 数据库更新
- 执行文件: `backend/migrations/update_alert_messages_simple.sql`
- 更新了8个通知模板的 `title_template`、`content_template`、`popup_title_template`、`popup_content_template`
- 所有模板都包含实时数据变量

### 代码修改
1. **risk_alert_service.py**:
   - 修改 `check_single_leg` 方法，添加 `binance_filled` 和 `bybit_filled` 参数
   - 在变量字典中包含所有必要的实时数据

2. **strategies.py**:
   - 修改 `send_single_leg_alert` 函数调用，传递 `binance_filled` 和 `bybit_filled`

3. **continuous_executor.py**:
   - 修改 `_send_single_leg_alert` 方法调用，传递 `binance_filled` 和 `bybit_filled`

### 通知渠道
1. **WebSocket推送**: 实时推送到前端，包含所有实时数据
2. **飞书通知**: 通过飞书机器人发送卡片消息，显示格式化的实时数据
3. **前端弹窗**: 显示提醒消息并播放提示音，展示详细的实时数据

### 冷却时间
所有提醒都有60秒冷却时间，防止重复提醒。

## 验证结果

✅ 所有8个模板已成功更新
✅ 消息格式符合用户要求
✅ 包含实时数据变量
✅ 数据库迁移执行成功
✅ 代码修改完成

## 示例消息

### 点差提醒示例
- 反向开仓: "反向已到货，请查收11111（当前点差：2.5）"
- 正向平仓: "正向需清货，请清货00000（当前点差：1.2）"

### 净资产提醒示例
- Binance: "*****A仓库需处理*****（当前：4500.00，阈值：5000.00）"
- 总资产: "*****紧急紧急货不足*****（当前：9500.00，阈值：10000.00）"

### 单腿提醒示例
- "B队员已瘸腿B（Binance：2.0000，Bybit：0.0000）"

## 后续工作

如需调整：
1. 修改 `backend/migrations/update_alert_messages_simple.sql`
2. 重新执行迁移脚本
3. 重启后端服务（如果需要）
