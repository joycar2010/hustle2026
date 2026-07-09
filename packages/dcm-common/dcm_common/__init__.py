"""DexCexMix 横切共享包。

来源与纪律:从 coin python-business 生产验证资产抽取(feishu_bot/notifier.throttle_ok/event_publisher),
去掉 ORM/settings 耦合,全部参数显式注入。告警通道函数绝不抛异常——吞掉并返回 (ok, detail)。
键空间统一前缀 dcm: ,与 coin 的 notif:*/spreads/engine:* 键空间物理隔离。
"""

__version__ = "0.1.0"
