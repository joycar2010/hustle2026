"""coincore:引擎与业务共用的核心门面包(coin 分家第一步)。

分家(绞杀者第三步)的路线:engine/ 剥离成独立服务前,先把它对 app.* 的 55 处
散射 import 收口到本包——门面纯转发零行为差异,收口后 engine 的依赖面=coincore
一个名字,物理拆仓时只需替换本包实现(指向共享库或独立 schema),engine 代码不再动。

纪律:引擎侧新代码只准 import coincore,不准直连 app.*;app 侧(业务/API)不受限。
"""
