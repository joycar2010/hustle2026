"""Pair Saga 执行器核心(V4.0 §6.4)—— 接口驱动的双腿状态机。
测试期用模拟交易所 + 内存 store 跑混沌;通过后换真交易所 adapter + PG store 即武装执行器。
不变量(混沌测试断言的目标):
  INV1 幂等:确定性 clientOrderId,ACK 丢失先查询再重试,绝不重复开仓;
  INV2 无单腿:一腿成一腿败 → LEG_IMBALANCE → 回滚已成腿,终态永不裸单腿;
  INV3 可恢复:mid-flight 崩溃后从 store 重建状态续跑,不双开;
  INV4 风险退出优先:reduce-only 应急平仓可越过正常配对流程。
"""
import asyncio


class VenueError(Exception):
    pass


# 腿状态
SENT, ACK, PARTIAL, CANCEL_PENDING, FILLED, UNKNOWN, ROLLED_BACK = \
    "SENT", "ACK", "PARTIAL", "CANCEL_PENDING", "FILLED", "UNKNOWN", "ROLLED_BACK"
# Saga 态
PROPOSED, RESERVED, OPENING, HEDGING, OPEN, CLOSING, CLOSED = \
    "PROPOSED", "RESERVED", "OPENING", "HEDGING", "OPEN", "CLOSING", "CLOSED"
LEG_IMBALANCE, QUARANTINED = "LEG_IMBALANCE", "QUARANTINED"

MAX_PLACE_RETRY = 3


def coid(saga_id, leg_idx, attempt_ns="open"):
    """确定性 clientOrderId:同一 (saga,leg,阶段) 永远同一个 id → 交易所端天然去重。"""
    return f"mix:{saga_id}:{leg_idx}:{attempt_ns}"


class SagaExecutor:
    """venue: VenueAdapter(async place/query/cancel);store: SagaStore(save/load/set_state)。"""

    def __init__(self, venue, store):
        self.venue = venue
        self.store = store

    async def _confirm_leg(self, saga_id, leg_idx, leg, ns="open"):
        """下单一腿并确认;ACK 丢失(TIMEOUT)先查询再决定重试 —— INV1 的核心。
        返回 True=已成交(FILLED),False=确认失败(达重试上限仍未成交)。"""
        cid = coid(saga_id, leg_idx, ns)
        for _ in range(MAX_PLACE_RETRY):
            # 每次重试前先查:确定性 cid 意味着上次可能其实已下到交易所
            q = await self.venue.query(cid)
            if q["status"] == FILLED:
                await self.store.save_leg(saga_id, leg_idx, cid, FILLED, q["filled"])
                return True
            if q["status"] in (ACK, PARTIAL):
                # 已挂单但未全成:等待/查询,不重复下单
                await self.store.save_leg(saga_id, leg_idx, cid, q["status"], q.get("filled", 0))
                q2 = await self.venue.query(cid)
                if q2["status"] == FILLED:
                    await self.store.save_leg(saga_id, leg_idx, cid, FILLED, q2["filled"])
                    return True
                continue
            # 未下到(NOTFOUND)→ 下单
            res = await self.venue.place(cid, leg)
            if res["status"] == FILLED:
                await self.store.save_leg(saga_id, leg_idx, cid, FILLED, res["filled"])
                return True
            if res["status"] == ACK:
                await self.store.save_leg(saga_id, leg_idx, cid, ACK, res.get("filled", 0))
                continue  # 下一轮查询确认
            if res["status"] == TIMEOUT:
                await self.store.save_leg(saga_id, leg_idx, cid, UNKNOWN, 0)
                continue  # ACK 丢失 → 下一轮先 query(幂等,不重复下)
            if res["status"] == REJECT:
                return False
        return False

    async def _rollback_leg(self, saga_id, leg_idx):
        """回滚已成腿(reduce-only 平掉)—— INV2:绝不留裸单腿。"""
        cid = coid(saga_id, leg_idx, "rollback")
        for _ in range(MAX_PLACE_RETRY):
            q = await self.venue.query(cid)
            if q["status"] == FILLED:
                await self.store.save_leg(saga_id, leg_idx, cid, ROLLED_BACK, 0)
                return True
            res = await self.venue.place(cid, {"reduce_only": True, "leg_idx": leg_idx})
            if res["status"] == FILLED:
                await self.store.save_leg(saga_id, leg_idx, cid, ROLLED_BACK, 0)
                return True
        return False  # 回滚失败 = 必须人工(fatal),外层置 QUARANTINED

    async def open_pair(self, saga_id, legs, resume=False):
        """开双腿。resume=True 从 store 重建续跑(崩溃恢复)—— INV3。"""
        existing = await self.store.load(saga_id) if resume else {}
        await self.store.set_state(saga_id, RESERVED)
        # 先薄盘口腿(leg0),再对冲腿(leg1);已 FILLED 的腿跳过(恢复幂等)
        await self.store.set_state(saga_id, OPENING)
        leg0_ok = existing.get(0, {}).get("state") == FILLED
        if not leg0_ok:
            leg0_ok = await self._confirm_leg(saga_id, 0, legs[0])
        if not leg0_ok:
            # leg0 都没成 → 无敞口,直接失败(无需回滚)
            await self.store.set_state(saga_id, CLOSED)
            return CLOSED
        await self.store.set_state(saga_id, HEDGING)
        leg1_ok = existing.get(1, {}).get("state") == FILLED
        if not leg1_ok:
            leg1_ok = await self._confirm_leg(saga_id, 1, legs[1])
        if leg1_ok:
            await self.store.set_state(saga_id, OPEN)
            return OPEN
        # leg0 成、leg1 败 → 单腿失衡 → 回滚 leg0
        await self.store.set_state(saga_id, LEG_IMBALANCE)
        if await self._rollback_leg(saga_id, 0):
            await self.store.set_state(saga_id, CLOSED)
            return CLOSED
        await self.store.set_state(saga_id, QUARANTINED)   # 回滚也失败=人工兜底
        return QUARANTINED


# place/query 返回的 status 常量
REJECT, TIMEOUT, NOTFOUND = "REJECT", "TIMEOUT", "NOTFOUND"
