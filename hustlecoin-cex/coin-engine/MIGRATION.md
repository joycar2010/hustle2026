# coin 分家二期:引擎物理拆分迁移手册

一期(已完成,coin 9589a47):coincore 门面收口——engine/ 55 处 app.* import 归一,
倒挂依赖修复,三机滚动验证全绿。引擎依赖面 = coincore 一个名字。

二期目标:engine/ + coincore/ 迁出 python-business 成独立部署单元 `coin-engine`,
业务 API(app/)与引擎不再同树;老 admin 对引擎降只读(启停走 dcm 代理链路)。

## 关键设计决策:模型层箭头翻转

现状死结:app.db.models 尾部反向 import engine.models(两层互相登记 Base metadata,
一期靠"Base 豁免直连"绕过三角循环)。物理拆分前必须翻转:

1. 模型真身迁入 coincore/models_def.py(引擎所需全部表:SubAccount/Position/
   SymbolRule/AccountSymbolRule/GlobalRules/FundRules/Blacklist/EngineState/
   TradeLog/...含 engine/models.py 三表),Base 在 coincore 定义;
2. app/db/models.py 改为 `from coincore.models_def import *`(app 侧零改动面);
3. engine/models.py 同样只 re-export——从此模型单一真身,循环消失;
4. 验证:两侧 alembic/create_all 的 metadata 是同一个对象(id 相等断言)。

## 迁移步骤(每步可回滚,迁移窗口执行)

M1 ✅ 本 scaffold(deploy 单元/unit/手册)——零生产影响
M2 模型箭头翻转(上述 1-4),python-business 原地验证+三机滚动(同一期方法)
M3 目录搬迁:engine/+coincore/ 复制到 ~/coin-engine/(独立 venv,requirements 见本目录),
   unit 改 WorkingDirectory/PYTHONPATH 指新树;**旧树保留不删=回滚即改回 unit**
M4 逐机切换:C(canary,shard 2)→观察 24h→B→A;每步断言 shard 心跳+worker RUNNING
   +业务 API 200+RECON v2 零孤儿
M5 老 admin 降只读:cex-business 的引擎启停端点加 feature flag(默认拒绝,提示走
   dcm 控制台代理链路);紧急逃生阀:flag 可秒开回写模式
M6 (可选)git 独立仓:subtree split 保留历史,推 coin-engine 分支/新 repo

## 回滚

任一步异常:unit 改回旧 WorkingDirectory + systemctl restart = 秒级回滚(旧树未动)。
M2 的模型翻转经门面隔离,回滚=git revert 单 commit + 三机同步。

## 风险清单

- 双树漂移:M3-M4 窗口内禁止改 engine 代码(改了必须双树同步)
- PYTHONPATH 阴影:新 unit 绝不能同时含新旧两树路径
- create_all 权限:引擎首启对新 metadata 做 create_all,若模型翻转有遗漏表会静默建错
  →M2 验证必须对比迁移前后 metadata.tables 键集全等
