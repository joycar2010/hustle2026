# coin-engine —— 独立部署单元(分家二期成果)

coin 套利引擎从 python-business 单体剥离后的独立树。`tree/` 是三机实际运行的源码
快照(engine/ + coincore/ 门面 + app 最小闭包 10 文件),独立 venv(requirements.lock)。

## 目录
- `tree/engine/`     引擎本体(orchestrator/worker/order_executor/fund/notify/trading)
- `tree/coincore/`   门面包:base(Base真身)/models_def(引擎三表真身)/db/config/models/notify/rules
- `tree/app/`        最小闭包:config + db.session/models{,_notify,_auth} + services.notifier/feishu_bot
- `tree/requirements.lock`  钉死版本(python3.11;从现役 venv freeze)
- `deploy/cex-engine@.service`  systemd 模板
- `MIGRATION.md`     M1-M6 迁移手册与回滚

## 运行
    python3.11 -m venv venv && venv/bin/pip install --no-deps -r tree/requirements.lock
    PYTHONPATH=<tree> venv/bin/python -m engine --shard-id=N

## 独立仓化(M6)
本目录经 `git subtree split --prefix=hustlecoin-cex/coin-engine -b coin-engine`
可剥成独立分支/仓库,历史保留。tree/ 与 python-business/{engine,coincore} 在双树
窗口期须同步(旧树是业务 API 依赖+回滚基线),M5 老 admin 降只读后旧树引擎写路径已封。
