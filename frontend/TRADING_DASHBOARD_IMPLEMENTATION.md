# 交易系统Dashboard重构实施指南

## 项目概述
基于参考图片重构 http://localhost:3000/DASHBOARD 界面，实现专业的跨平台套利交易系统。

## 已完成的基础架构
✅ TradingDashboard.vue - 主布局框架
✅ 所有核心组件文件已创建
✅ 基础样式配置（深色模式 #1a1d21）

## 需要更新的组件清单

### 1. AccountStatusPanel.vue (左侧边栏)
**当前状态**: 基础账户信息展示
**需要更新**:
- 顶部添加"当前用户总盈利"卡片
- 分离Binance和Bybit MT5账户为独立卡片
- 每个账户卡片添加：
  - 连接状态指示器（绿点/红点）
  - 操作按钮：连接/断开（绿色/红色）、禁用（灰色）、删除（红色）
  - 完整数据字段（9项）
- 底部添加"系统提醒"区域
  - 账户净值提醒
  - 爆仓价位提醒
  - 反向套利提醒
  - 正向套利提醒
  - 风控状态

### 2. SpreadChart.vue (顶部中央)
**当前状态**: 基础图表
**需要更新**:
- 实现双线图表（Chart.js）
  - 绿色线：Bybit做多盈亏曲线
  - 红色线：Binance做多盈亏曲线
- 时间轴：约1分钟监控周期
- 纵轴：盈亏值（USDT），0线为平衡点
- 实时数据更新（1秒间隔）

### 3. MarketCards.vue (顶部左右两侧)
**当前状态**: 基础市场卡片
**需要更新**:
- 左侧：Bybit MT5 - XAUUSD.s
  - 实时价格（大字体）
  - ASK价格
  - BID价格
  - 连接状态指示
  - 卡顿心跳线（显示卡顿次数）
- 右侧：Binance - XAUUSDT
  - 相同布局和数据结构

### 4. SpreadDataTable.vue (顶部中间列)
**当前状态**: 基础数据表
**需要更新**:
- 最多显示12行
- 三列布局：
  - 左列：时间戳
  - 中列：做多Bybit点差（绿色）
  - 右列：做多Binance点差（红色）
- 实时滚动更新
- 数据高亮变化

### 5. StrategyPanel.vue (中部两个面板)
**当前状态**: 基础策略面板
**需要更新**:

#### 反向套利策略（左侧，type="reverse"）
- 顶部信息栏：
  - 做多Bybit点差（绿色大字）
  - Binance可用资产
  - Bybit MT5可用资产
- 配置区域：
  - M币设置（整数输入）
  - 启用开仓/停用开仓（绿色/红色切换按钮）
  - 启用平仓/停用平仓（绿色/红色切换按钮）
  - 开仓数据同步数量
  - 平仓数据同步数量
  - 保存按钮（黄色）
- 阶梯配置列表（最多5级）：
  - 每级包含：启用开关、删除按钮、开仓价、阈值、下单数量限制
  - 添加阶梯按钮
  - 保存策略按钮（黄色）

#### 正向套利策略（右侧，type="forward"）
- 相同结构，但：
  - 顶部显示做多Binance点差（红色）
  - 其他配置相同

### 6. OrderMonitor.vue (底部左侧)
**当前状态**: 基础订单监控
**需要更新**:
- 挂单记录表格
- 列：时间、平台、方向、价格、数量、状态
- 实时更新
- 状态颜色编码

### 7. RiskDashboard.vue (底部中间)
**当前状态**: 基础风险仪表盘
**需要更新**:
- 各账户保证金风险预警
- 三个指标卡片：
  - 保证金率（进度条）
  - 风险率（进度条）
  - 账户权益（数值）
- 颜色编码：绿色（安全）、黄色（警告）、红色（危险）

### 8. ManualTrading.vue (底部右侧)
**当前状态**: 基础手动交易面板
**需要更新**:
- 紧急处理手动交易执行面板
- 字段：
  - 平台账户（下拉选择：Binance/Bybit MT5）
  - 方向（买入/卖出按钮）
  - 买入价（输入框）
  - 数量（输入框）
  - 所需保证金（自动计算显示）
  - 执行交易按钮（大按钮，黄色）

## 颜色规范
```css
/* 背景色 */
--bg-primary: #1a1d21
--bg-secondary: #1e2329
--bg-card: #252930

/* 功能色 */
--color-active: #0ecb81 (绿色 - 启用/做多Bybit)
--color-danger: #f6465d (红色 - 停止/做多Binance)
--color-warning: #f0b90b (黄色 - 保存按钮)
--color-info: #2196F3 (蓝色 - 信息)

/* 边框 */
--border-color: #2b3139
```

## 交互规范
1. 所有启用状态使用绿色高亮
2. 停止或平仓使用红色
3. 保存按钮统一使用黄色
4. 数据变动需要明显的视觉反馈（闪烁或颜色变化）
5. 按钮hover效果：亮度增加10%
6. 输入框focus效果：边框高亮

## 数据更新频率
- 实时价格：1秒
- 点差数据：1秒
- 图表数据：1秒
- 账户数据：5秒
- 订单记录：2秒

## API接口（待实现）
```javascript
// 账户数据
GET /api/v1/accounts/summary
GET /api/v1/accounts/binance
GET /api/v1/accounts/bybit

// 市场数据
GET /api/v1/market/prices
GET /api/v1/market/spread
WS /ws/market/realtime

// 策略配置
GET /api/v1/strategies
POST /api/v1/strategies
PUT /api/v1/strategies/:id
DELETE /api/v1/strategies/:id

// 订单管理
GET /api/v1/orders
POST /api/v1/orders/manual
GET /api/v1/orders/pending

// 风险监控
GET /api/v1/risk/metrics
GET /api/v1/risk/alerts
```

## 实施步骤
1. ✅ 创建基础组件结构
2. 🔄 更新AccountStatusPanel（左侧边栏）
3. ⏳ 更新SpreadChart（双线图表）
4. ⏳ 更新MarketCards（价格卡片）
5. ⏳ 更新SpreadDataTable（点差数据表）
6. ⏳ 更新StrategyPanel（策略配置）
7. ⏳ 更新OrderMonitor（订单监控）
8. ⏳ 更新RiskDashboard（风险仪表盘）
9. ⏳ 更新ManualTrading（手动交易）
10. ⏳ 集成实时数据
11. ⏳ 测试和优化

## 注意事项
- 所有数字使用等宽字体（font-mono）
- 价格保留2位小数
- 百分比保留2位小数
- 大数字使用千分位分隔符
- 响应式设计：最小宽度1920px
- 性能优化：使用虚拟滚动处理大量数据

## 测试清单
- [ ] 左侧边栏账户切换
- [ ] 实时价格更新
- [ ] 图表数据渲染
- [ ] 策略配置保存
- [ ] 阶梯添加/删除
- [ ] 手动交易执行
- [ ] 风险预警触发
- [ ] 订单状态更新
- [ ] 连接状态切换
- [ ] 系统提醒显示

---
**当前状态**: 基础架构已完成，正在实施详细功能
**下一步**: 按照上述步骤逐个更新组件