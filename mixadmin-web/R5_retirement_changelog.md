# R5 退役变更清单

**日期**: 2026-07-26  
**分支**: mix (本地构建树,待推送 origin/mix)  
**升级包**: MIX-V6.2-OPEX-AUTO-PATCH-03 §18.R5  

## 变更摘要
- **删除**: 27 个路由定义 + 27 个组件文件
- **行数**: 108 → 74 (-34 行)
- **文件数**: 62 → 35 (-27 个 .vue)

## 删除的路由(27 个)

### QH 经营壳(24 个)
```
dashboard, bi, product, users, accounts, leads, trials, orders,
points, agents, staff, coupons, campaigns, contests, iap, overview,
params, notify, sitemgr, operators, datamgr, chat, legs, recon
```

### C3 旧页(3 个)
```
mix/slots, mix/c3, mix/legacy
v6.1/strategy-workbench/slots (别名)
legacy/c3s (别名)
```

## 删除的组件文件(27 个)

### src/views/ (24 个)
```
Dashboard.vue, Bi.vue, Product.vue, Users.vue, Accounts.vue,
Leads.vue, Trials.vue, Orders.vue, Points.vue, Agents.vue,
Staff.vue, Coupons.vue, Campaigns.vue, Contests.vue, Iap.vue,
Overview.vue, Params.vue, Notify.vue, SiteMgr.vue, Operators.vue,
DataMgr.vue, Chat.vue, Legs.vue, Recon.vue
```

### src/views/mix/ (3 个)
```
MixSlots.vue, MixC3.vue, MixV6Legacy.vue
```

## 保留(关键组件)
- ✅ MixDashboard.vue (Mix 持仓执行面板,/wall/exec 内容体)
- ✅ MixOps.vue (系统状态,/system 路由)
- ✅ MixV6Console.vue (旧中控,暂保留待修复引用)
- ✅ /wall/* 只读外接墙全部路由
- ✅ /deals redirect (兼容链接)

## 备份文件
- `src/router/index.js.bak_R5_before_20260726_150831`
- `src/views_bak_R5_20260726_150831.tar.gz`

## 门槛审查结果
- ✅ 零动态引用 (全源码扫描)
- ✅ 无后端专属 API
- ✅ 升级包明确列为 READY_TO_REMOVE
- ⚠️ MixV6Console 暂不删除 (RiskStatusBar + Layout 仍引用)

## 下一步
1. npm run build 验证构建
2. 部署服务器测试
3. 修复 MixV6Console 引用后再删除该路由

---
**执行人**: Claude Code  
**审计报告**: R5_retirement_audit.md
