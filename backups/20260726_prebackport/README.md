# 20260726 改前备份版(MIX-V6.2-OPEX-AUTO-PATCH-03 R1 回灌前的生产真相快照)

来源:C 机 57.181.130.126 `/data/mix/`,2026-07-26 10:55 UTC 只读打包(未动任何原目录)。
服务器本地同款副本:`/data/mix/backups/20260726_prebackport/`(含未推送的 .env 原件)。

| 文件 | 内容 |
|---|---|
| backend_src_full.tar.gz | `/data/mix/backend` 全量源码(**含全部 .bak 与 fastlane.py 等 server-ahead-of-git 文件**;排除 venv/`__pycache__`/.env) |
| mixadmin_web_dist.tar.gz | mix.hustle2026.xyz 在线前端 dist(mixadmin-web) |
| user_web_dist.tar.gz | user.hustle2026.xyz 在线前端 dist |
| mix_web_dist.tar.gz | 旧 mix-web dist(域名归并前的用户壳,留档) |
| c4_dir.tar.gz | `/data/mix/c4` |
| mix-ws-hub.bin | Rust WS hub 部署二进制(mix-ws.service@8201;**源码权威在本仓 qh 分支 `qh_ws_hub/`**) |
| pg_mix_main_20260726.dump.gz | PostgreSQL `mix_main` 逻辑备份(pg_dump -Fc) |
| pg_dcm_main_20260726.dump.gz | PostgreSQL `dcm_main` 逻辑备份(mix 后端只读依赖库) |
| dotenv_keys_sanitized.txt | backend/.env 的**键名清单**(脱敏;原件只留服务器) |
| conf/ | nginx 四份 vhost(mix/user/8443/coin-compat)+ mix-backend/mix-ws/mix-l1lite systemd unit |
| SHA256SUMS.txt | 服务器侧生成的校验和 |

恢复要点:backend 需另建 venv(`pip install -r requirements`);.env 从服务器副本或 KMS 重建;DB 用 `gunzip -c | pg_restore -d <db>`。
