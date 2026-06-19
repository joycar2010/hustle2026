"""MT5 临时停市熔断注册表 (20260620)

背景 / 根因 (cq002 北京06-20 01:xx 15手单腿事件):
  MT5 经纪商发生【盘中临时停市】(全年罕见, 这次约从北京1点持续到正常收盘5点, 4小时)。
  此期间:
    -币安 (7x24) 平空腿正常成交;
    - MT5 平仓腿被 order_send 拒单, retcode=10018 (TRADE_RETCODE_MARKET_CLOSED);
    => 单腿。
  而既有防线 (preflight 探 symbol_info.trade_mode==FULL) 在这种瞬态/盘中停市下【会撒谎】:
  实测停市全程 106 次探测全报 trade_mode=FULL / trade_allowed=True, 一次没拦住。
  事后还查实: 桥【没有 order_check 干跑端点】, 且 /mt5/tick 时间戳在"临时停市/日级休市/
  周末休市"三种情况下都冻结、无法区分。=> 不存在"零副作用又不撒谎"的恢复探针。

设计 (与用户逐轮敲定的约束对齐):
  唯一不撒谎的停市信号 = order_send 的真实回执 retcode=10018。
  1) 触发: B 侧真实下单/平仓回 10018 -> 把该 (account_id) 标记 frozen, 并记 frozen_at。
  2) 熔断: continuous_executor 主循环下单前 (preflight 旁) 查 frozen -> defer 本轮, 不下 A 单。
            杜绝"停市期 A 侧继续成交、B 侧补不上"持续制造单腿 (本次实测停市后系统仍盲目挂了
            十几笔币安单, 仅因 maker 未成交才侥幸没扩大)。
  3) 解冻 (保守, 不主动探测——因无可靠零副作用探针):
       a. 锚定"下一次正常开市": preflight 复开市检测确认 trade_mode 由非FULL->FULL 时,
          调用 clear() 解冻 (复用既有复开市预热, 行为与每天正常开市/周末复开市完全一致)。
       b. 时间兜底: 距 frozen_at 超过 MAX_FREEZE_S 强制失效 (防状态烂在内存里误伤次日)。
       c. 进程级兜底: 状态【只存内存】, 服务重启即清 (实测频繁重启), 绝不跨日/跨重启残留。
  4) 绝不自动补仓: 本模块只负责"停下单 + 提供冻结态", 存量单腿一律交由解冻后的实时双边
     对账 + 仅告警, 由用户决定 (用户明确手动交易独立自由, 系统无权按旧数字擅自补单)。

注意: 状态按 account_id 维度 (而非 bridge), 与 _get_trading_bridge_url 解析无关, 简单稳。
"""
import time
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# account_id(str) -> frozen_at(monotonic seconds). 仅存内存, 重启即清。
_frozen_at: Dict[str, float] = {}

# 时间兜底上限: 单次冻结最长存活时间。超过即强制失效, 防"解冻信号没来"时状态烂在内存
# 误伤次日。取 6h: 比这次实测 4h 停市留足余量, 又远短于"冻结跨到第二天正常开市"。
MAX_FREEZE_S: float = 6 * 3600.0


def mark_frozen(account_id: str, reason: str = "retcode=10018") -> bool:
    """B 侧真实回 10018 时调用。返回 True 表示这是一次【新】冻结(用于触发一次性告警)。"""
    if not account_id:
        return False
    aid = str(account_id)
    now = time.monotonic()
    was_frozen = aid in _frozen_at
    _frozen_at[aid] = now
    if not was_frozen:
        logger.error(
            f"[MT5_FREEZE] account={aid} 检测到 MT5 临时停市({reason}) -> 冻结下单, "
            f"等正常开市自动解冻(或{MAX_FREEZE_S/3600:.0f}h兜底)"
        )
        return True
    return False  # 已在冻结中, 仅刷新时间戳, 不重复告警


def is_frozen(account_id: str) -> bool:
    """主循环下单前查询。内含时间兜底: 超 MAX_FREEZE_S 自动失效。"""
    if not account_id:
        return False
    aid = str(account_id)
    ts = _frozen_at.get(aid)
    if ts is None:
        return False
    if (time.monotonic() - ts) > MAX_FREEZE_S:
        # 时间兜底失效: 防状态烂在内存误伤次日
        _frozen_at.pop(aid, None)
        logger.warning(f"[MT5_FREEZE] account={aid} 冻结超 {MAX_FREEZE_S/3600:.0f}h 兜底失效(强制解冻, 转由 preflight 把关)")
        return False
    return True


def clear(account_id: str, reason: str = "正常开市") -> None:
    """解冻。由 preflight 复开市检测(trade_mode 非FULL->FULL)调用, 锚定下一次正常开市。"""
    if not account_id:
        return
    aid = str(account_id)
    if _frozen_at.pop(aid, None) is not None:
        logger.info(f"[MT5_FREEZE] account={aid} 解冻({reason})")


def frozen_age(account_id: str) -> Optional[float]:
    """返回已冻结秒数(供告警文案), 未冻结返回 None。"""
    ts = _frozen_at.get(str(account_id)) if account_id else None
    return (time.monotonic() - ts) if ts is not None else None
