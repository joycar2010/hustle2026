"""配对仓位状态机定义(armed 模式的执行骨架,shadow 模式只用其词汇表)。

testgo 蓝本的移植要点(每条都是学费):
- OPENING:先进**薄盘口腿**(流动性差的所先成交,厚腿追单容易薄腿追单难);
  单腿超时(DCM_DP_LEG_TIMEOUT_SEC)未双腿齐 → ROLLBACK(平掉已成腿,绝不裸奔等第二腿);
- 防重入三道:inflight 置位(下单前置 true+watchdog 复位)/Redis 单飞锁 NX+TTL/
  下单前指纹二次确认(同 symbol+方向+数量 在途即拒);
- 一切状态迁移只信实盘(fetch_order/fetch_position),HTTP 200 与内存状态不作数;
- 体外对账(GOLD_RECON 模式)独立于本状态机随 risk-ledger 跑:DB 非终态 vs 两所实盘,
  孤儿腿=一所有仓另一所无仓 → fatal;
- 锁/告警/归因键一律 (venue, market, symbol, account)。

状态图:
  FLAT --route target>0--> OPENING --双腿实盘确认--> OPEN
  OPENING --单腿超时/失败--> ROLLBACK --已成腿平掉实盘确认--> FAILED(留审计)
  OPEN --route target=0/draining/退出信号--> CLOSING --双腿平仓实盘确认--> CLOSED
"""
from enum import Enum


class PairState(str, Enum):
    OPENING = "OPENING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    ROLLBACK = "ROLLBACK"


# 合法迁移表:任何不在表内的迁移=编程错误,直接 fatal 告警(状态机不静默容错)
ALLOWED_TRANSITIONS: dict[PairState, set[PairState]] = {
    PairState.OPENING: {PairState.OPEN, PairState.ROLLBACK, PairState.FAILED},
    PairState.OPEN: {PairState.CLOSING},
    PairState.CLOSING: {PairState.CLOSED, PairState.FAILED},
    PairState.ROLLBACK: {PairState.FAILED, PairState.CLOSED},
    PairState.CLOSED: set(),
    PairState.FAILED: set(),
}


def assert_transition(cur: PairState, nxt: PairState) -> None:
    if nxt not in ALLOWED_TRANSITIONS[cur]:
        raise RuntimeError(f"illegal pair state transition {cur} -> {nxt}")
