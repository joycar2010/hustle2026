# 执行安全测试床 (V1.1 §18 首版, 2026-07-16)

## 用途
在不触外网/不触真交易所/不写业务表的前提下, 锻炼生产执行链的安全机制。
每次改动 continuous_executor / order_executor_v2 / broadcast_tasks / 桥契约后必跑。

## 运行
    cd /data/hustle2026/backend
    venv/bin/python tests/testbed/run_scenarios.py
    # 期望输出: ===== 测试床结果: 9/9 PASS =====

## 组件
- `fake_bridge.py` — 模拟 MT5 桥 HTTP 契约(含实际成交四量字段), 行为可编排
  (done/partial/reject/hang), 可独立起服务(--port)或经 ASGITransport 内嵌。
- `run_scenarios.py` — 9 个安全场景(S1-S9), 全部针对真实生产代码, 币安侧在
  base_executor 方法边界用可编排假体。

## 场景清单
S1 watcher预注册不丢早到成交 | S2 预算不足不下单 | S3 监控被杀shield撤单仍发出
S4 补腿精确量+记账+幂等 | S5 空clientOrderId拒补+告警 | S6 桥超时UNKNOWN不盲发
S7 REST核查有限重试 | S8 桥契约四量字段 | S9 部分成交循环补挂+真实均价

## 待扩展(M2前)
- Fake Binance HTTP 面(fapi端点仿真, 供 BinanceFuturesClient 客户端级测试)
- §18.2 完整故障注入矩阵(进程四切点击杀/DB暂停/Redis重启/时钟漂移)
- 10,000 随机化执行序列状态机属性测试(重复对冲必须为0)
