# ✅ 移动端H5适配实施检查清单

## 📋 实施前准备

- [ ] 阅读 `MOBILE_ADAPTATION_GUIDE.md`（详细方案）
- [ ] 阅读 `INTEGRATION_GUIDE.md`（集成步骤）
- [ ] 阅读 `QUICK_REFERENCE.md`（快速参考）
- [ ] 查看 `LAYOUT_COMPARISON.md`（布局对比）
- [ ] 确认 Vue 3 版本 ≥ 3.2
- [ ] 确认 Node.js 版本 ≥ 16
- [ ] 备份现有代码到 Git 分支

---

## 🔧 文件创建（3个新组件）

- [ ] 创建 `EmergencyManualTrading.vue`
  - 路径：`frontend/src/components/trading/`
  - 功能：紧急手动交易
  - 高度限制：400px

- [ ] 创建 `RecentTradingRecords.vue`
  - 路径：`frontend/src/components/trading/`
  - 功能：最近交易记录
  - 高度限制：400px

- [ ] 创建 `FloatingActionButtons.vue`
  - 路径：`frontend/src/components/trading/`
  - 功能：浮动按钮（账户+风险）
  - 显示条件：移动端（<1024px）

---

## 🔄 文件更新（4个现有组件）

### TradingDashboard.vue
- [ ] 备份原文件为 `TradingDashboard_Backup.vue`
- [ ] 导入新组件：
  - [ ] `EmergencyManualTrading`
  - [ ] `RecentTradingRecords`
  - [ ] `FloatingActionButtons`
- [ ] 添加组件引用：`const recentRecordsRef = ref(null)`
- [ ] 添加事件处理：`handleOrderExecuted()`
- [ ] 更新模板结构（参考 `TradingDashboard_New.vue`）
- [ ] 添加移动端样式：
  - [ ] 侧边栏隐藏（`display: none`）
  - [ ] 主内容区域垂直排列（`flex-direction: column`）
  - [ ] 组件宽度 100%（`width: 100%`）
  - [ ] 组件高度限制（`max-height`）

### OrderMonitor.vue
- [ ] 备份原文件为 `OrderMonitor_Backup.vue`
- [ ] 在 `<style scoped>` 末尾添加移动端样式：
  ```css
  @media (orientation: portrait), (max-width: 750px) {
    .order-monitor-container {
      width: 100%;
      max-height: 350px;
      overflow-y: auto;
    }
  }
  ```
- [ ] 测试滚动功能

### SpreadDataTable.vue
- [ ] 备份原文件为 `SpreadDataTable_Backup.vue`
- [ ] 在 `<style scoped>` 末尾添加移动端样式：
  ```css
  @media (orientation: portrait), (max-width: 750px) {
    .spread-table-container {
      width: 100%;
      max-height: 350px;
      overflow-y: auto;
    }
  }
  ```
- [ ] 测试滚动功能

### StrategyPanel.vue
- [ ] 备份原文件为 `StrategyPanel_Backup.vue`
- [ ] 更新顶部信息栏结构：
  - [ ] 添加 `.top-info-bar` 类
  - [ ] 添加 `.info-item` 类
- [ ] 在 `<style scoped>` 末尾添加移动端样式：
  ```css
  @media (orientation: portrait), (max-width: 750px) {
    .top-info-bar {
      flex-direction: column;
    }
    .strategy-panel-container {
      max-height: 300px;
      overflow-y: auto;
    }
  }
  ```
- [ ] 测试信息栏垂直排列

---

## 🧪 功能测试

### PC端测试（≥1024px）
- [ ] 打开 `http://localhost:3000/trading-dashboard`
- [ ] 左侧边栏显示（账户状态 + 导航）
- [ ] 右侧边栏显示（风险管理）
- [ ] 策略面板左右排列
- [ ] OrderMonitor 和 SpreadDataTable 左右排列
- [ ] 浮动按钮隐藏
- [ ] 所有功能正常工作

### 移动端测试（<750px 或竖屏）
- [ ] 使用 Chrome DevTools 移动端模拟
- [ ] 选择设备：iPhone 12 / Pixel 5
- [ ] 侧边栏隐藏
- [ ] 浮动按钮显示在右下角
- [ ] 组件垂直排列顺序正确：
  1. [ ] 反向套利策略
  2. [ ] MarketCards
  3. [ ] 正向套利策略
  4. [ ] OrderMonitor
  5. [ ] SpreadDataTable
  6. [ ] EmergencyManualTrading
  7. [ ] RecentTradingRecords
- [ ] 每个组件高度限制生效
- [ ] 超出内容可滚动
- [ ] 滚动流畅（≥60fps）

### 浮动按钮测试
- [ ] 点击"账户"按钮
  - [ ] 弹出 AccountStatusPanel
  - [ ] 遮罩层半透明
  - [ ] 点击遮罩层关闭
  - [ ] 点击关闭按钮关闭
- [ ] 点击"风险"按钮
  - [ ] 弹出 Risk 组件
  - [ ] 遮罩层半透明
  - [ ] 点击遮罩层关闭
  - [ ] 点击关闭按钮关闭
- [ ] 两个弹窗互斥显示
- [ ] 按钮点击区域 ≥ 44px × 44px

### 交互功能测试
- [ ] 紧急交易下单
  - [ ] 选择交易平台
  - [ ] 输入下单数量
  - [ ] 点击"买入开多"
  - [ ] 点击"卖出开空"
  - [ ] 状态消息显示
- [ ] 最近交易记录
  - [ ] 初始加载显示
  - [ ] WebSocket 实时更新
  - [ ] 点击"查看更多"跳转
- [ ] 订单执行后刷新
  - [ ] EmergencyManualTrading 下单
  - [ ] RecentTradingRecords 自动刷新

### 平板测试（768px - 1023px）
- [ ] 左侧边栏显示（宽度缩小）
- [ ] 右侧边栏隐藏
- [ ] 浮动按钮显示
- [ ] 布局自适应

---

## 🎨 视觉验收

### 颜色
- [ ] 主背景色：#1a1d21
- [ ] 组件背景色：#1e2329
- [ ] 边框颜色：#2b3139
- [ ] 买入颜色：#0ecb81
- [ ] 卖出颜色：#f6465d
- [ ] 警告颜色：#f0b90b

### 字体
- [ ] 移动端字体大小适中（12px-16px）
- [ ] 数字使用等宽字体
- [ ] 标题加粗显示

### 间距
- [ ] 组件间距：16px
- [ ] 内边距：12px-16px
- [ ] 按钮内边距：12px

### 动画
- [ ] 浮动按钮悬停效果
- [ ] 弹窗淡入淡出
- [ ] 脉冲动画（紧急模式）

---

## 📱 兼容性测试

### 浏览器
- [ ] Chrome（最新版）
- [ ] Safari（iOS 14+）
- [ ] Firefox（最新版）
- [ ] Edge（最新版）
- [ ] 微信浏览器

### 设备
- [ ] iPhone 12/13/14
- [ ] iPhone SE
- [ ] iPad
- [ ] Android 手机（Pixel, Samsung）
- [ ] Android 平板

### 屏幕方向
- [ ] 竖屏模式
- [ ] 横屏模式（宽度<750px 时仍为移动端布局）

---

## 🚀 性能验收

### 加载性能
- [ ] 首屏加载时间 < 3秒
- [ ] 组件懒加载正常
- [ ] 图片资源优化

### 运行性能
- [ ] 滚动帧率 ≥ 60fps
- [ ] 交互响应时间 < 100ms
- [ ] 内存占用合理（< 100MB）

### 网络性能
- [ ] WebSocket 连接稳定
- [ ] 断线自动重连
- [ ] 数据实时更新

---

## 🐛 问题排查

### 如果组件不显示
- [ ] 检查导入路径
- [ ] 检查组件注册
- [ ] 查看浏览器控制台错误

### 如果样式不生效
- [ ] 检查媒体查询条件
- [ ] 检查 CSS 优先级
- [ ] 清除浏览器缓存

### 如果浮动按钮不显示
- [ ] 检查屏幕宽度
- [ ] 检查 z-index
- [ ] 检查 display 属性

### 如果 WebSocket 连接失败
- [ ] 检查后端服务
- [ ] 检查网络连接
- [ ] 查看控制台错误

---

## 📝 文档完善

- [ ] 更新项目 README.md
- [ ] 添加移动端适配说明
- [ ] 更新组件文档
- [ ] 添加截图示例

---

## 🎯 上线前检查

### 代码质量
- [ ] 移除所有 console.log
- [ ] 移除调试代码
- [ ] 代码格式化（Prettier）
- [ ] ESLint 检查通过

### 资源优化
- [ ] 图片压缩
- [ ] CSS 压缩
- [ ] JavaScript 压缩
- [ ] 启用 Gzip

### 安全检查
- [ ] XSS 防护
- [ ] CSRF 防护
- [ ] API 认证
- [ ] 敏感信息加密

### 备份和回滚
- [ ] 创建 Git 标签
- [ ] 备份数据库
- [ ] 准备回滚脚本
- [ ] 通知相关人员

---

## ✅ 最终验收

- [ ] 所有测试通过
- [ ] 性能指标达标
- [ ] 兼容性验证完成
- [ ] 文档更新完成
- [ ] 团队评审通过
- [ ] 用户验收测试（UAT）通过

---

## 📞 问题反馈

如遇到问题，请按以下顺序排查：

1. 查看 `INTEGRATION_GUIDE.md` 常见问题章节
2. 检查浏览器控制台错误信息
3. 查看 `MOBILE_ADAPTATION_GUIDE.md` 技术细节
4. 联系开发团队技术支持

---

## 🎉 完成标志

当以下所有条件满足时，移动端H5适配项目完成：

✅ 所有新组件创建完成
✅ 所有现有组件更新完成
✅ PC端功能不受影响
✅ 移动端布局完全适配
✅ 所有交互功能正常
✅ 性能指标达标
✅ 兼容性测试通过
✅ 文档更新完成
✅ 团队评审通过
✅ 用户验收通过

---

**检查清单版本**：v1.0
**最后更新**：2026-03-05
**维护者**：前端开发团队

---

## 📊 进度追踪

| 阶段 | 任务数 | 完成数 | 进度 | 状态 |
|------|--------|--------|------|------|
| 准备阶段 | 7 | 0 | 0% | ⏳ 待开始 |
| 文件创建 | 3 | 0 | 0% | ⏳ 待开始 |
| 文件更新 | 4 | 0 | 0% | ⏳ 待开始 |
| 功能测试 | 50+ | 0 | 0% | ⏳ 待开始 |
| 视觉验收 | 12 | 0 | 0% | ⏳ 待开始 |
| 兼容性测试 | 15 | 0 | 0% | ⏳ 待开始 |
| 性能验收 | 9 | 0 | 0% | ⏳ 待开始 |
| 上线准备 | 12 | 0 | 0% | ⏳ 待开始 |
| **总计** | **112+** | **0** | **0%** | **⏳ 待开始** |

---

**使用说明**：
1. 按顺序完成每个检查项
2. 完成后在 `[ ]` 中打勾 `[x]`
3. 遇到问题记录在问题反馈章节
4. 定期更新进度追踪表
