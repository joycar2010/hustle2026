"""PgSagaStore(V4.0 §5.3)—— Saga/腿状态 PostgreSQL 持久化,崩溃后可从此重建续跑。
与 MemStore 同接口(save_leg/load/set_state),供 exec_core 生产驱动。dcm_main.exec_saga(JSONB legs)。
"""
import json


class PgSagaStore:
    def __init__(self, pool, mode="armed"):
        self.pool = pool
        self.mode = mode

    async def save_leg(self, sid, idx, cid, st, filled):
        # UPSERT saga 行,legs JSONB 按 idx 设子键(单表原子写,恢复即读)
        await self.pool.execute(
            "INSERT INTO exec_saga(saga_id, legs, mode, updated_at) "
            "VALUES($1, jsonb_build_object($2::text, $3::jsonb), $4, now()) "
            "ON CONFLICT (saga_id) DO UPDATE SET legs = exec_saga.legs || jsonb_build_object($2::text, $3::jsonb), "
            "updated_at=now()",
            sid, str(idx), json.dumps({"coid": cid, "state": st, "filled": filled}), self.mode)

    async def load(self, sid):
        row = await self.pool.fetchrow("SELECT legs FROM exec_saga WHERE saga_id=$1", sid)
        if not row or not row["legs"]:
            return {}
        legs = row["legs"] if isinstance(row["legs"], dict) else json.loads(row["legs"])
        return {int(k): v for k, v in legs.items()}

    async def set_state(self, sid, st):
        await self.pool.execute(
            "INSERT INTO exec_saga(saga_id, state, mode, updated_at) VALUES($1,$2,$3,now()) "
            "ON CONFLICT (saga_id) DO UPDATE SET state=$2, updated_at=now()", sid, st, self.mode)
