"""V6.2 R3 StrategyPlaybook(§6)——版本化静态白话原理,只读。

- 内容随 git 发布(不进 CMS/LLM 后台实时改,§8.2);改内容=改此文件+部署=可审计。
- 三层:一句白话 / 钱从哪赚·最容易哪亏·何时退出 / 专业层(公式与机制注记)。
- 铁律:全部标注"预期收益,非无风险";编号=DB product_catalog 权威(非方案文档错位编号)。
"""
from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer

router = APIRouter(tags=["v6-playbooks"])

PLAYBOOK_VERSION = "pb-20260726-1"

_PB = {
    "C1": {
        "name": "期现收费(Spot-Perp Carry)",
        "plain": "买一份现货、同时做空同币永续,主要赚持续为正的资金费(现货可叠加真实理财收益)。",
        "earn_from": "永续空头收的资金费净额;现货侧 earn 利息。",
        "lose_from": "资金费转负并持续;基差走阔;退出时双腿摩擦(费+滑点);保证金占用。",
        "exit_rule": "资金费翻负达阈值轮次(autopilot 实测 2 轮自动 close);或摊费闸判定收不回成本。",
        "pro": "净收益=Σfunding−开平费−滑点−(借贷/占用成本)+earn;执行链=fastlane→Intent/Saga;C1 分支带 funding 闸+摊费闸。",
    },
    "C2.H": {
        "name": "HARVEST 跨所资金费收割",
        "plain": "同一个币,在资金费低(或收钱)的所做多、资金费高的所做空,赚两边资金费的净差。",
        "earn_from": "双边资金费净差(按结算周期归一日化)。",
        "lose_from": "四笔手续费(两开两平);两所结算时间错位;费差衰减到不够付费;单所风险(限提/停服)连坐双腿。",
        "exit_rule": "费差衰减低于阈值并持续(gap_decay);费差翻向(gap_flip);venue 风险事件触发减险。",
        "pro": "E=Σ(fr_short−fr_long)×名义−4×fee−|basis变动|;xv 影子环同口径滚动验证(capture≈75%)。",
    },
    "C2.C": {
        "name": "CONVERGENCE 跨所收敛",
        "plain": "跨所基差偏离到统计高分位时建对冲仓,持有吃资金费 carry 等偏离回归。",
        "earn_from": "持有期资金费净差为主,回归时基差变动为辅。",
        "lose_from": "结构性改变不再收敛;快进快出吃不到 carry(真金实证教训:净亏根因);退出深度不足。",
        "exit_rule": "E 闸离散化+持有到结算闸;manager target=close 收敛出场。",
        "pro": "信号=c2c_signal 7日分位/z-score(SHADOW);开仓走 phase-autopilot→fastlane,日帽与总帽约束。",
    },
    "C2.P": {
        "name": "PRE_CARRY 人工预判",
        "plain": "人工判断币种所处阶段,预判点差/资金费将扩张,用小预算提前布局——这不是有硬锚的套利,依赖人的判断。",
        "earn_from": "判断兑现后的点差扩张+后续资金费。",
        "lose_from": "论点失效;点差持续反向扩大;砸盘/强平;退出深度差。",
        "exit_rule": "论点失效条件写进研判案件;复核时间到未验证=退出。",
        "pro": "仅 HOUSE_RND 资金池;研判先行→DRY_RUN→Passkey→Pair Saga;不自动 armed。",
    },
    "C3.S": {
        "name": "借币点差(Spread Carry)",
        "plain": "借入现货卖出、同时做多永续对冲,主要赚开仓和平仓时的点差,扣掉借币利息。",
        "earn_from": "开/平点差;持有期 signed funding 若为正另计。",
        "lose_from": "无券可借/被召回(-3045);借息累计;买回/还币失败卡债务;高点差币常无券、有券币点差被压平(库存vs点差命门)。",
        "exit_rule": "点差收敛达标即平;还币闸+裸空安全网兜底;开仓态还币拆腿被 409 闸拦。",
        "pro": "E=开平点差−借息−费;V6 写路=C3.S.V6 单发监督;老引擎并行对比中(legacy_compare)。",
    },
    "C3.R": {
        "name": "利率 Carry(Rate)",
        "plain": "同一笔借币对冲结构,当 signed funding+借息+earn 的净额为正时按利率路由持有。",
        "earn_from": "signed funding+earn−借息 的正净额。",
        "lose_from": "funding 符号翻转;借息上浮;净差前列币常无券(首轮判决实证)。",
        "exit_rule": "净额转负持续;宇宙=授权账 C3R 行∩可借。",
        "pro": "信号面=lending-advisor 三率日化;榜单持久化 c3r_ranking_sample。",
    },
    "C4": {
        "name": "期现交割(Spot-Future)",
        "plain": "买现货、空同币交割合约,到期强制结算把基差锁死——有硬锚的收敛。",
        "earn_from": "开仓时锁定的年化基差(实仓 +190~380bps 级)。",
        "lose_from": "到期前流动性变差;保证金被基差波动挤压(币押结构可零强平);近月合约=费死陷阱。",
        "exit_rule": "默认持有到交割(settle);提前退出须过闸复核实时基差。",
        "pro": "执行=c4_exec 人工 CLI(两钥匙+五闸 fail-closed);监控=R12-C4 强平线+到期<7天预警;现货腿账面回补不入衍生品归并。",
    },
    "C5": {
        "name": "永续交割(Perp-Future)",
        "plain": "永续与交割合约配对,吃到期锚定收敛,同时承受持有期浮动资金费。",
        "earn_from": "开仓锁定的两腿价差年化;funding 若同向为正另计。",
        "lose_from": "持有期 funding 反向累计;到期前点差波动;两腿规格不兼容(张数/乘数)。",
        "exit_rule": "持有到交割为主;funding 反向累计超预算=提前评估。",
        "pro": "okx inverse 币押结构已真金验证(liqPx=空,零强平);feed 张×ctVal 换算已修。",
    },
    "C6": {
        "name": "交割配对(Future-Future 日历价差)",
        "plain": "同所同币两个不同到期日的交割合约对开,赚期限结构错位——目前只测量,不交易。",
        "earn_from": "(理论)远近合约年化基差之差的回归。",
        "lose_from": "(理论)两腿费用与保证金;交割合约流动性极薄;近月年化被小分母放大出假信号。",
        "exit_rule": "MEASURE 阶段:c6_calendar 探针小时采样,长窗口+剔除<14天近月后再判是否值得建。",
        "pro": "ann_bps=(P_far/P_near−1)/days×365×1e4;数据在 dcm_main.c6_calendar_samples。",
    },
    "O1": {
        "name": "现金流优化器(Cashflow Optimizer)",
        "plain": "不自己持仓——在 C1-C3 已有仓位的真实腿上比较资金费/借息/理财,把现金流挪到更优的一边。",
        "earn_from": "同一仓位结构下的现金流差值(不产生独立 PnL 归因)。",
        "lose_from": "符号/期限/申赎窗口算错;账户可用性判断错导致挪不回来。",
        "exit_rule": "leg-aware 插件逻辑,不抢仓不加风险。",
        "pro": "原'三率'(S4)降级为插件;数据层已建,执行回路未启用(PLANNED)。",
    },
}

_DISCLAIMER = "以上为预期收益机制说明,不是无风险承诺;任何回路都可能亏损,以风控闸与退出纪律为准。"


@router.get("/playbooks/{product_code}")
async def get_playbook(product_code: str, _who=Depends(require_viewer)):
    pb = _PB.get(product_code)
    if not pb:
        raise HTTPException(404, f"无 {product_code} 的 playbook(编号以 product_catalog 为准)")
    return {"product_code": product_code, "version": PLAYBOOK_VERSION,
            "disclaimer": _DISCLAIMER, **pb}


@router.get("/playbooks")
async def list_playbooks(_who=Depends(require_viewer)):
    return {"version": PLAYBOOK_VERSION, "codes": sorted(_PB.keys()), "disclaimer": _DISCLAIMER}
