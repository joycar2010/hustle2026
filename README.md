# DexCexMix — 多所多域费率类收益组合系统

微服务矩阵(五平面):数据面 feed-cex/feed-dex/sampler → 决策面 decision → 执行面 5 引擎 → 风控面 risk-ledger → 资金调度 treasury,加 gateway(API/admin)。服务间只允许 **Redis 总线 + Postgres 配置表** 两种耦合,禁止引擎间同步 HTTP。

## 拓扑(东京 ap-northeast-1a, VPC 10.0.0.0/16)

| 机器 | 内网 | EIP | 角色 |
|---|---|---|---|
| DexCexMix-A-data | 10.0.1.212 | 52.193.224.137 | Redis 总线 + dcm_tsdb + feeds |
| DexCexMix-B-exec | 10.0.1.103 | 54.65.42.207 | 5 引擎 + signer-dex + treasury |
| DexCexMix-C-ctrl | 10.0.1.12 | 57.181.130.126 | dcm_main(PG) + decision + risk-ledger + gateway |

SSH: `ssh -i ~/.ssh/cex-trading-key2.pem ec2-user@<EIP>`

已收编存量:coin 引擎(engine-coin)经 `dcm-coin-bridge` 旁车挂号(coin 业务机 57.183.43.62,
零侵入只读 dcm_ro)——`dcm:hb:coin-bridge` / `dcm:engine:coin:state` / `dcm:engine:coin:positions`。

## 目录

- `packages/dcm-common/` — 横切共享包(飞书/节流/总线事件/心跳),从 coin 生产资产抽取,零 ORM 依赖
- `services/<svc>/` — 各微服务(每服务一个 systemd 单元,挂 dexcexmix.slice + 自己的 MemoryMax)
- `deploy/bootstrap_server.sh` — 新机初始化(swap/slice/redis/pg)
- `deploy/deploy.sh <svc> <host> [port]` — 部署+真验证(新 pid + HTTP 200 + json 断言)
- `deploy/units/` — systemd 单元

## 部署纪律(继承 coin 事故教训)

1. 单一 git 真源,FF-only,绝不 force / 绝不 scp 补丁式改服务器文件;
2. 部署成功的定义 = 新 pid + 真 HTTP 断言,不是"命令跑完";
3. 服务必须自带心跳键 `dcm:hb:<svc>`(TTL 90s),停更即告警;
4. 锁/告警去重/对账归因一律 (venue, market, symbol, account) 组合键;
5. 读端点/风控进程绝不加猜测式自愈;
6. 新表必须走迁移 + GRANT 检查,禁 create_all。
