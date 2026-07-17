# V6.2 Frame → Route → Contract 映射表（P0 交付物 · 唯一映射权威）

> 规约：Pencil 帧出现的按钮若不在服务端 allowed_actions 中，只能禁用展示。
> 每个垂直切片合并前，对照本表 + v62-acceptance-checklist.md 逐条勾。

## 组件（Pencil States 区 ↔ 代码组件）

| 组件 | Pencil 帧 | 代码落点 | 状态数 | 数据契约 |
|---|---|---|---|---|
| StatusBar | B7J44C | components/V6StatusBar.vue（改造） | 7态:正常/观察/暂停新增/只减仓/维护/过期/训练 | control_snapshot.effective_capabilities + site_maintenance_state + training |
| WorkItemRow | CurTL | components/v62/WorkItemRow.vue（新建） | 7态:默认/选中/提交中/阻断/过期/异常/完成 | WorkItem v2.2（含五字段+allowed_actions） |
| ValueCell | u9Uw0/ValueCell行 | composables/useDict.js dvText/dvClass（收拢为组件） | 7态 | data_state 八态契约（§6.2） |
| PrimaryAction | u9Uw0/PrimaryAction行 | components/v62/PrimaryAction.vue（新建） | 5态:可用/禁用/加载/需认证/执行失败 | allowed_actions[0].kind==primary + still_allowed |
| ProcessRail | eTSxn/流程条示例 | components/v62/ProcessRail.vue（新建） | 5态:未开始/当前/完成/异常/受阻 | counts + workflow_stage 分布 |
| DetailDrawer | eTSxn/抽屉行 五变体 | components/v62/DetailDrawer.vue（新建,变体=slot） | 5变体:机会/持仓/风险/账务/研判 | WorkItem + 各域投影;技术详情折叠段固定 |
| EmptyState | u9Uw0/EmptyState四态 | components/v62/EmptyState.vue（新建） | 4态:无任务/未接入/等待数据/无权限 | data_state + 角色 |
| MobileActionBar | u9Uw0/MobileActionBar四态 | MixPhone.vue 内轻实现（手机专属,备案例外） | 4态:查看/确认/减险/不可操作 | allowed_actions(手机白名单过滤后) |

## 页面帧 → 路由

| Frame | 视口 | route | role | 主动作 | 状态覆盖要求 |
|---|---|---|---|---|---|
| 今日工作三栏（N2 新画,基于 joknS+hExte 合体） | 1440×900 | /mix/today | OPERATOR | 行主动作(服务端) | 空/过期/错误/维护/训练 |
| 三显示器墙 | 1920×1080 | /wall/market|exec|risk（保留免登录） | wall token | 只读 | 过期 |
| HCD9I 平板横 | 1280×800 | /mobile | OPERATOR(+Passkey) | 审批/两步平仓 | 空/过期/维护 |
| 平板竖 | 800×1280 | /mobile | 同上 | 同上 | 同上 |
| wzu8n 操作员手机 | 390×844 | /m | OPERATOR_MOBILE_LIMITED | 减险白名单 | 空/过期/离线 |
| QG9qS→JYMLu 投资人手机(暗色已实现) | 390×844 | user域 / | investor JWT | 只读+账目确认 | 空/维护 |
| oBZch Legacy Compare | 1920 | /mix/legacy | SUPER_ADMIN | 只读 | 差异>0 置顶 |

## 手机独立轻实现备案（P0 §5 例外条款）
/m 壳刻意不加载桌面 bundle：MobileActionBar 及行卡片为手机专属渲染，
但**必须消费同一 WorkItem 契约与同一 allowed_actions**——逻辑共享、渲染独立，不算双实现。
