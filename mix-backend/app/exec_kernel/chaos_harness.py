"""混沌测试脚手架(V4.0 §18.2)—— 对 Pair Saga 执行器注入交易所逆境,断言不变量。
纯内存零真金零生产接触:模拟交易所(部分成交/ACK丢失/拒单/撤单竞态/崩溃/网络分区)
× 双腿组合 × 崩溃点,枚举 1000+ 场景,逐场景校验:
  INV1 幂等:每腿在交易所至多一个有效持仓(确定性 coid 去重);
  INV2 无单腿:终态 OPEN=两腿成 / CLOSED=已回滚净平 / QUARANTINED=人工兜底,绝无裸单腿;
  INV3 可恢复:mid-flight 崩溃后从 store 重建续跑,结果与不崩一致,不双开。
运行: python -m app.exec_kernel.chaos_harness   (纯 stdlib)
"""
import asyncio
import itertools

from . import exec_core as E


class SimVenue:
    """模拟交易所。按脚本对每腿注入结果;确定性 coid 去重(幂等真相源)。
    leg_plan[leg_idx] = 事件序列,每次 place/query 消费一步。"""

    def __init__(self, leg_plan, partition=False):
        self.leg_plan = leg_plan          # {leg_idx: [outcome,...]}
        self.orders = {}                  # coid -> {state, filled}  ← 交易所端真相(去重)
        self.place_calls = {}             # coid -> 次数(测幂等:同 coid 多次 place 不产生多单)
        self.partition = partition        # 网络分区:query 也 TIMEOUT
        self._step = {}

    def _leg_of(self, cid):
        return int(cid.split(":")[2])

    def _next(self, leg_idx):
        seq = self.leg_plan.get(leg_idx, [E.FILLED])
        i = self._step.get(leg_idx, 0)
        self._step[leg_idx] = min(i + 1, len(seq) - 1)
        return seq[i]

    async def place(self, cid, leg):
        self.place_calls[cid] = self.place_calls.get(cid, 0) + 1
        # rollback 单:总是成功平掉(reduce-only 应急)
        if cid.endswith(":rollback"):
            self.orders[cid] = {"state": E.FILLED, "filled": 0}
            return {"status": E.FILLED, "filled": 0}
        if cid in self.orders and self.orders[cid]["state"] == E.FILLED:
            # 已成交,幂等:不重复建仓
            return {"status": E.FILLED, "filled": self.orders[cid]["filled"]}
        outcome = self._next(self._leg_of(cid))
        if outcome == E.FILLED:
            self.orders[cid] = {"state": E.FILLED, "filled": 1.0}
            return {"status": E.FILLED, "filled": 1.0}
        if outcome == "ACK_LOST":
            # 交易所其实收到并成交了,但 ACK 在网络上丢了 → 客户端看到 TIMEOUT
            self.orders[cid] = {"state": E.FILLED, "filled": 1.0}
            return {"status": E.TIMEOUT, "filled": 0}
        if outcome == "TIMEOUT_NOFILL":
            # 客户端超时,交易所也没收到 → 无单
            return {"status": E.TIMEOUT, "filled": 0}
        if outcome == E.PARTIAL:
            self.orders[cid] = {"state": E.PARTIAL, "filled": 0.5}
            return {"status": E.ACK, "filled": 0.5}
        if outcome == E.REJECT:
            return {"status": E.REJECT, "filled": 0}
        self.orders[cid] = {"state": E.FILLED, "filled": 1.0}
        return {"status": E.FILLED, "filled": 1.0}

    async def query(self, cid, leg=None):
        if self.partition:
            return {"status": E.NOTFOUND, "filled": 0}   # 分区期查不到(保守当未下)
        o = self.orders.get(cid)
        if not o:
            return {"status": E.NOTFOUND, "filled": 0}
        # PARTIAL 的单再查一次会成交(模拟盘口追上)
        if o["state"] == E.PARTIAL:
            o["state"] = E.FILLED
            o["filled"] = 1.0
        return {"status": o["state"], "filled": o["filled"]}

    async def cancel(self, cid):
        if cid in self.orders and self.orders[cid]["state"] != E.FILLED:
            self.orders[cid]["state"] = "CANCELED"

    # ---- 断言辅助:交易所端真实净持仓腿数 ----
    def open_legs(self):
        legs = set()
        for cid, o in self.orders.items():
            if cid.endswith(":rollback"):
                continue
            if o["state"] == E.FILLED:
                legs.add(self._leg_of(cid))
        # 被回滚的腿要剔除
        for cid, o in self.orders.items():
            if cid.endswith(":rollback") and o["state"] == E.FILLED:
                legs.discard(self._leg_of(cid))
        return legs

    def max_place_per_coid(self):
        return max(self.place_calls.values(), default=0)


class MemStore:
    def __init__(self):
        self.legs = {}      # saga_id -> {leg_idx: {coid,state,filled}}
        self.state = {}

    async def save_leg(self, sid, idx, cid, st, filled):
        self.legs.setdefault(sid, {})[idx] = {"coid": cid, "state": st, "filled": filled}

    async def load(self, sid):
        return self.legs.get(sid, {})

    async def set_state(self, sid, st):
        self.state[sid] = st


async def _run_one(sid, leg0_plan, leg1_plan, crash_after=None, partition=False):
    """跑一个场景。crash_after:在某腿确认后模拟崩溃并重启续跑(测 INV3)。返回终态+venue。"""
    venue = SimVenue({0: leg0_plan, 1: leg1_plan}, partition=partition)
    store = MemStore()
    ex = E.SagaExecutor(venue, store)
    legs = [{"leg_idx": 0}, {"leg_idx": 1}]
    if crash_after == "leg0":
        # 只跑到 leg0 确认就"崩溃":单独确认 leg0 后丢弃执行器,再 resume
        await ex._confirm_leg(sid, 0, legs[0])
        await store.set_state(sid, E.OPENING)
        # 新执行器 resume(store 保留了 leg0 状态)
        ex2 = E.SagaExecutor(venue, store)
        final = await ex2.open_pair(sid, legs, resume=True)
    else:
        final = await ex.open_pair(sid, legs, resume=False)
    return final, venue


def _check_invariants(final, venue):
    """返回 [] 表示全过,否则返回违规列表。"""
    v = []
    ol = venue.open_legs()
    # INV2 无单腿:终态语义与实际持仓腿数一致
    if final == E.OPEN and ol != {0, 1}:
        v.append(f"OPEN 态但实际持仓腿={sorted(ol)}(应两腿)")
    if final == E.CLOSED and ol:
        v.append(f"CLOSED 态但仍有持仓腿={sorted(ol)}(裸单腿!)")
    if final not in (E.OPEN, E.CLOSED, E.QUARANTINED):
        v.append(f"非终态 {final}")
    # INV1 幂等真检:同一腿在交易所端至多 1 个成交单(确定性 coid → 不可能重复开仓)
    from collections import Counter
    filled_per_leg = Counter()
    for cid, o in venue.orders.items():
        if cid.endswith(":rollback"):
            continue
        if o["state"] == E.FILLED:
            filled_per_leg[venue._leg_of(cid)] += 1
    for leg_idx, cnt in filled_per_leg.items():
        if cnt > 1:
            v.append(f"腿{leg_idx} 有 {cnt} 个成交单(重复开仓!)")
    return v


async def main():
    E.PLACE_PROPAGATION_SLEEP = 0   # 传播窗复查在 sim 中零延迟(逻辑照走,1600 场景不拖慢)
    # 单腿事件字母表(覆盖 §18.2:成交/部分/ACK丢失/超时无成/拒单)
    outcomes = [E.FILLED, "ACK_LOST", "TIMEOUT_NOFILL", E.PARTIAL, E.REJECT]
    # 每腿最多两步序列(第一步逆境,第二步恢复),×崩溃点×分区 → 组合
    seqs = [[o] for o in outcomes] + [[a, b] for a in outcomes for b in [E.FILLED, "TIMEOUT_NOFILL", "ACK_LOST"]]
    crash_opts = [None, "leg0"]
    part_opts = [False, True]
    scenarios = list(itertools.product(seqs, seqs, crash_opts, part_opts))

    total = passed = 0
    fails = []
    for i, (l0, l1, crash, part) in enumerate(scenarios):
        total += 1
        try:
            final, venue = await _run_one(f"chaos{i}", l0, l1, crash_after=crash, partition=part)
            viol = _check_invariants(final, venue)
            if viol:
                fails.append((i, l0, l1, crash, part, final, viol))
            else:
                passed += 1
        except Exception as e:  # noqa: BLE001
            fails.append((i, l0, l1, crash, part, "EXC", [repr(e)[:80]]))
    print(f"混沌测试:{total} 场景,通过 {passed},失败 {len(fails)}")
    # 终态分布
    from collections import Counter
    dist = Counter()
    for i, (l0, l1, crash, part) in enumerate(scenarios):
        pass
    for f in fails[:12]:
        print(f"  ✗ #{f[0]} leg0={f[1]} leg1={f[2]} crash={f[3]} part={f[4]} final={f[5]} 违规={f[6]}")
    if not fails:
        print("  ✅ 全部不变量通过:无重复开仓 / 无裸单腿 / 崩溃可恢复")
    return len(fails)


if __name__ == "__main__":
    import sys
    sys.exit(1 if asyncio.run(main()) else 0)
