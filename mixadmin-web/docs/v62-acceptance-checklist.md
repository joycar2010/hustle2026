# V6.2 验收清单（每批次合并前逐条勾 · 方案 §12 固化）

## 每批次通用（N1-N5 全部适用）
- [ ] 契约先行：服务端字段/权限先落，前端只消费不猜
- [ ] Pencil 帧先于代码（或同批完成），按钮不超出 allowed_actions
- [ ] 空态/过期/错误态/维护态四态齐备（对照 States 区组件矩阵）
- [ ] 1440 / 1280 / 800 / 390 四视口截图验收，无溢出无遮挡
- [ ] 旧页面仅回退显示层，无第二写入口
- [ ] 部署防呆：build 前确认 cwd；包内含 index.html 才允许 --delete
- [ ] 画板批次完成后 cp 日期备份（pen 回退事故铁律）

## 终验（N5 完成时全项过）
- [ ] 新操作员登录 10 秒内找到最高优先级任务
- [ ] 任一允许动作 ≤3 次点击
- [ ] 一个工作项全过程不需要主动切换模块
- [ ] 返回后筛选、选中行、展开状态恢复（URL/session 分层）
- [ ] 服务端未确认前，工作项不在页面假成功迁移（提交中三态）
- [ ] 默认页面零内部术语（Saga/RECON/Epoch 只在专家折叠层）
- [ ] 所有组件覆盖 正常/空/过期/故障/维护/训练 状态
- [ ] 旧 C3.S 始终只读，不与 V6.2 双写（writer lease 唯一）
- [ ] 未通过训练认证：禁新增风险（开仓/加仓/新借币/提额/规则发布），减险永放行
- [ ] 训练认证用 training_certification{version,scope,passed_at}，非永久布尔

## 批次专项
### N1
- [ ] WorkItem v2.2 五字段:what_happened/system_did/completion_condition/next_trigger/still_allowed
- [ ] 禁用三行式：暂不能 X / 原因 / 仍可做（still_allowed 直读字段）
- [ ] selection store：URL={work_item_id,view,filters,tab}；session={scroll,展开,列宽,抽屉宽}
- [ ] 八组件代码化并替换 ≥1 个现有消费点

### N2
- [ ] /mix/today 合体页：ProcessRail+三视图(三栏/单栏页签/墙聚焦)+六段抽屉
- [ ] 候选送工作台=提交中三态，失败原地回滚
- [ ] /wall/* 免登录墙保留，屏1/2/3按钮=聚焦/弹窗语义

### N3
- [ ] 四入口菜单+右上系统管理；旧 URL 30-60 天跳转
- [ ] 风险/收益/交易从工作项深链进入（query 直达筛选）

### N4
- [ ] 训练模式：回放快照源+六课目状态机判定+certification 门禁（服务端）
- [ ] 手机 /m 四页签；减险 before/after 预演
- [ ] 投资人手机触控数据点

### N5
- [ ] 旧菜单隐藏与 C3.S 十四天零差异钟对齐
- [ ] Legacy Compare 按 V6.2 组件重制
