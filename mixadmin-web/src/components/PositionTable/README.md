# PositionTable — 币种主行 ↳子账户子行 两级虚拟滚动表（右键菜单版）

1:1 对齐 coin.hustle2026.xyz/dashboard：**币种主行（全账户聚合）→ ↳缩进子账户子行（内联标签，执行账户 + 主/子徽章）**；无卡片层。全自动系统的手工干预全部收进**右键菜单**（右键 / 行尾 ⋮ / 移动端长按，三入口同一菜单）。

## 文件

| 文件 | 职责 |
|---|---|
| `types.ts` | 契约：`PositionRow` / `AccountSubRow`（executingAccount + accountKind）/ `PhaseCode` / `MenuItem` / `PlatformType` |
| `strategyColumns.ts` | 注入表：主/子行插槽列（≤6）、行内高频钮（INLINE_ACTIONS）、右键菜单（CONTEXT_MENUS）、账户菜单（ACCOUNT_MENUS，cex vs kms_wallet） |
| `useInflight.ts` | 防重入：发起瞬间置位 + 8s watchdog 强制复位 |
| `VirtualPositionTable.vue` | 虚拟滚动两级表 + 右键/长按菜单 + 倒计时渐变 + 规则列 |

## 设计铁律

1. **phase 直接渲染后端状态码**，前端绝不推断（单腿盲/僵尸假运行教训）。
2. **排序键用后端字段**（`opened_at` / `pnl`），默认平铺发起时间早→晚。
3. **内联标签**：标签跟着值走；策略插槽列 ≤6，超出进详情弹层。
4. **子行显示执行账户**：hedge_via_master 的对冲腿挂平台主账号就显示主账号（「主」徽章），是子账户显示子账户（「子」徽章）——`executingAccount + accountKind` 由后端下发。
5. **干预全在菜单**：行内只留 coin 验证过的高频文字钮（S3 移/还）；菜单分组，danger 项（强制平仓/手动还币/清除/冻结）红字 + `confirm: true` 强制确认浮层。
6. **防重入**：同 key 在途直接吞掉；watchdog 复位仅解锁 UI，结果以 WS 对账。
7. **倒计时预警**：`keyDeadlineTs` <30min → 主行整行左→右金色渐变 + 金边。
8. **规则列**：`ruleScope` 显示「通用规则/单独规则」，点击 emit `ruleOverride` → 规则中心·币种覆盖弹窗（同一份数据，不是第二套规则）。
9. **账户列表复用**：rows=主账号、subRows=子账户 即账户列表页；`platformType === 'kms_wallet'` 的行菜单自动换 KMS 钱包管理模块（发起/审批分离 + 白名单 + 限额铁律不因并表放松）。
10. **通知归全局**：策略只声明事件与级别；飞书间隔/次数/冷却/令牌桶节流在「通知设置」模块统一配置。

## 收益图表约定（配套页面）

净值曲线全站替换为**收益柱形图**：日/周/月粒度 × 30天/90天/半年/全部范围，正绿负红、柱顶标注极值，「累计净值」折线作为可切换副视图。ECharts bar + label；周/月为前端对日数据聚合。

## 接入

vite8 + vue3.5，无 element-plus 硬依赖；lucide-vue-next 渲染 `STRATEGY_META[code].icon` 与菜单图标。WS 增量：替换 `rows` 引用即可；>500 行改 rowId patch + 手动 trigger。
