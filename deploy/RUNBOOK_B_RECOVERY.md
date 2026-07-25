# B 机(执行面)灾难恢复预案 — Warm Standby Runbook

**版本**: v1.0 (2026-07-25, 阶段三韧性补课)
**对象**: B 机 54.65.42.207 / 10.0.1.103 — **执行面唯一持钥机**(五所 API 密钥+下单能力)
**RTO 目标**: < 2 小时(手动重建);**RPO**: 状态零丢失(所有权威状态在 PG 10.0.1.12 + Redis 10.0.1.95,B 机本身无状态)

---

## 0. 核心事实(为什么 B 死了钱是安全的)

- **B 机无权威状态**:saga/intent/持仓账本在 dcm_main PG(C机 10.0.1.12),运行态在 Redis(95)。
- **B 死 = 停新开,存量仓冻结在交易所**,不会消失。manager 心跳消失后 RECON 把接管仓如实转 NAKED 告警(fail-loud),risk-ledger hb-missing 告警(exec-manager/recon/opener/repair 全缺)。
- **人工兜底始终可用**:任何一台机器 + API 密钥 + canary_c2.py --arm --close 可平任何仓。

## 1. 运行服务清单(2026-07-25 快照,12 个运行中)

| 服务 | 职责 | 恢复优先级 |
|------|------|-----------|
| dcm-exec-manager | 持仓管理 owner-of-record | **P0** |
| dcm-exec-recon | 对账+armed 自动修复+reaper | **P0** |
| dcm-account-snapshot | 五所账户快照(policy 输入) | **P0** |
| dcm-exec-runner | 快线执行桥 | P1 |
| dcm-exec-opener | 开仓候选(shadow) | P1 |
| dcm-exec-repair | G2 救援腿(shadow) | P1 |
| dcm-cred-agent | KMS/凭证 | **P0**(其他服务依赖) |
| dcm-borrow-monitor / dcm-transfer-monitor / dcm-io-monitor | 借币/划转/充提监控 | P2 |
| dcm-pnl-recorder / dcm-lending-advisor | 账单/顾问 | P2 |
| (已退役 unit 勿启: engine-basis / engine-dualperp / engine-lending / hl-backfill) | | |

## 2. 恢复步骤(新 EC2 或修复后的 B)

```bash
# ① 基础:Amazon Linux 2023, 同 VPC 子网(须能达 10.0.1.12 PG / 10.0.1.95 Redis), python3.11
git clone -b dexcexmix https://github.com/joycar2010/hustle2026.git dexcexmix-src
mkdir ~/dexcexmix && cp -r dexcexmix-src/* ~/dexcexmix/src/   # 布局:git 无 src/ 前缀,服务器有
# ⚠️ 运行时铁律:exec 服务跑 ~/dexcexmix/ 根目录副本 —— 从 src/services/exec-kernel/ 拷到根:
cp ~/dexcexmix/src/services/exec-kernel/{manager,recon,opener,runner,repair,exec_core,real_venue,store,policy_client,canary_c2,recon_orphan_handler,recon_qty_handler}.py ~/dexcexmix/
python3.11 -m venv ~/dexcexmix/venv && ~/dexcexmix/venv/bin/pip install asyncpg redis httpx

# ② 密钥/环境:.env 异地备份在 C 机 ec2-user@10.0.1.12:~/backups/b-machine-env-20260725 (0600)
scp ec2-user@10.0.1.12:~/backups/b-machine-env-20260725 ~/dexcexmix/.env && chmod 600 ~/dexcexmix/.env
# ⚠️ 若密钥已疑泄露:先在五所控制台轮换 API key,再更新 .env(credential_epoch 会自动 bump)

# ③ units:git deploy/units/ 有部分;缺的按 dcm-carry-advisor 模板改 ExecStart(根目录脚本用
#    WorkingDirectory=~/dexcexmix + ExecStart=venv/bin/python <name>.py)
sudo systemctl daemon-reload
# ④ 白名单:新机公网 IP 须加入币安(等五所)API 白名单——**这是最长的外部依赖,先做**
# ⑤ 按优先级启动:cred-agent → account-snapshot → exec-recon(先看对账!) → exec-manager → 其余
sudo systemctl start dcm-cred-agent dcm-account-snapshot
sudo systemctl start dcm-exec-recon      # 先跑对账:确认 expected vs 实盘一致再启 manager
sudo systemctl start dcm-exec-manager dcm-exec-opener dcm-exec-runner dcm-exec-repair
```

## 3. 恢复验证清单(全绿才算恢复)

1. `dcm:hb:exec-manager` / `dcm:hb:exec-recon` 心跳恢复(risk-ledger LEDGER_OK 无 missing)
2. `dcm:exec:recon` matched=在场腿数、breaks=0(有 breaks 先人工审,勿急着 armed)
3. `dcm:account:{venue}` 五所 ok=true(白名单生效证明)
4. manager 发布态 pairs 与恢复前一致(对照 PG exec_saga OPEN 行)
5. 快线冒烟:极小额 canary_c2 dry(门控拒单+query 幂等)

## 4. 密钥备份纪律

- B .env 唯一异地副本:C 机 `~/backups/b-machine-env-YYYYMMDD`(0600)。**每次改 B .env 后必须刷新备份**(本 runbook 建立时快照 2026-07-25)。
- .env 永不入 git;真值只在 B 机 + C 机备份。
- KMS/cred-agent 相关材料按其自身文档(G-C 安全闸,不在本 runbook 范围)。

## 5. 演练记录

| 日期 | 类型 | 结果 |
|------|------|------|
| 2026-07-25 | 预案建立+.env 异地备份落地 | runbook v1.0 |
| (待) | 真实重建演练(新 EC2 走一遍) | 建议扩量前做一次 |
