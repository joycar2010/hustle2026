# HustleCoin Mix 后端骨架（从 openapi.yaml 展开）

给后端同学：这是 `contracts/openapi.yaml` 的可运行 FastAPI 骨架。逐个 router 把 `TODO(backend)` 换成真实实现即可，**前端不动**——把 `VITE_MIX_API` 指向本服务（默认 `:8200`）。

## 运行
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8200
# 校验：curl :8200/api/v1/health  与  /api/v1/meta/enums
```
自带 Swagger：`http://127.0.0.1:8200/docs`。

## 结构与契约映射
| 文件 | 契约职责 |
|---|---|
| `app/enums.py` | **状态枚举单一来源**。`/meta/enums` 直接序列化本文件。改状态机只改这里；前端绝不推断 phase。 |
| `app/schemas.py` | Pydantic 模型，与前端 `types.ts` 逐字段对齐（币种行 columnLabels=标签、子行 values=数值同列位；子行 executingAccount+accountKind）。 |
| `app/deps.py` | 鉴权依赖：operator/admin/wall token；`enforce_view` 强制 merged\|self 显式。 |
| `app/security_kms.py` | **KMS 四道安全闸**（白名单/限额/发起≠审批/私钥不出 KMS）。 |
| `app/routers/positions.py` | 坑位行；写操作 202 + WS 对账；FROZEN 强制平仓 → 409。 |
| `app/routers/rules.py` | 五级作用域，唯一行 + 唯一索引，保存热生效 3s。 |
| `app/routers/accounts.py` | 两级账户 + KMS 审批流。 |
| `app/routers/misc.py` | 监控/黑名单/币管理/报表/告警/通知。 |
| `app/routers/me.py` | 用户端 `/me/*`；merged\|self 必填。 |

## 五条必须守住的契约不变量（前端已依赖）
1. `phase` 直接下发状态码，不推断（历史事故：采信 HTTP200 致单腿盲/僵尸假运行）。
2. `/positions` 缺 `view/sort/dir` → **400**；排序键用后端字段。
3. 写操作 **202** 受理，结果走 WS `position:updates`；状态机拒绝 **409**（FROZEN 强制平仓）。
4. `/me/*` 的 `view` 缺失 → **400**（merged 默认值泄漏事故）。
5. KMS 转账 **发起人 ≠ 审批人** 强制，签名在 KMS 内完成——见下节安全评审。

## KMS 审批流安全评审：见 `SECURITY_KMS.md`
