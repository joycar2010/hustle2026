# KMS 审批流 · 后端安全评审

并入账户列表的是 **UI 入口**，不是安全边界的降级。链上转账走一条独立的、比 CEX 操作更严的路径。

## 威胁模型
| 威胁 | 对策（后端强制） |
|---|---|
| 操作员账号被盗后自转 | 发起 ≠ 审批（`approve_transfer` 硬校验 `approver_id != initiator_id`），审批需独立权限位 `kms_approve` |
| 目标地址被篡改 | 出款地址白名单，非白名单一律 422，白名单变更本身需审批 + 审计 |
| 大额一次性抽干 | 单笔上限 `per_tx_cap` + 当日累计 `daily_cap` 双闸 |
| 私钥泄漏 | 私钥永不出 KMS；后端只发签名请求、收签名结果与 txid；进程内存无私钥 |
| 事后抵赖 / 取证 | append-only `kms_audit`：发起/审批/签名/冻结每步落库，不可删，与 AI 审计四件套同一审计域 |
| 重放 | 每笔转账 `idempotencyKey` + 状态机（pending_approval→executed 单向，不可回退重签） |

## 状态机（不可跳步）
```
draft →[闸1 白名单 + 闸2 限额]→ pending_approval →[闸3 发起≠审批 + 权限位]→ signing(KMS) → executed
                                                    ↘ rejected（记审计）
紧急冻结 freeze：任意态 → frozen（冻结后禁止一切出款，仅超管可解）
```

## 落地检查清单（上线前逐项过）
- [ ] `kms_approve` 权限位仅授予 2+ 名审批人，与发起操作员集合不相交
- [ ] 白名单、per_tx_cap、daily_cap 存 DB 且变更走审批；不得写死在代码/env
- [ ] `daily_cap` 的"当日"按钱包 + UTC 日切，跨所不共享额度
- [ ] KMS 签名超时/失败 → 回滚到 pending_approval，绝不静默置 executed（对齐"回滚静默失败升裸空告警"教训）
- [ ] audit 表 append-only（DB 权限层面禁 UPDATE/DELETE），与业务库物理隔离更佳
- [ ] 冻结按钮独立鉴权，且冻结事件即时飞书 FATAL（绕过节流）
- [ ] 前端只是入口：所有校验后端重做一遍，绝不信任前端传来的 feasible/限额

## 与前端契约的对应
- 发起转账 `POST /kms/transfers` → `202 {state:"pending_approval"}`（前端显示"转账待审批"标签）
- 审批 `POST /kms/transfers/{id}/approve` → `200 {state:"executed", auditId}`（前端弹审计号）
- 校验失败 → `422`（白名单/限额），`403`（发起=审批）—— 前端 ElMessage 原样回显
