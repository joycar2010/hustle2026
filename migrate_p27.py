# migrate_p27: 会员积分+员工归因 第一阶段 schema(幂等, 纯加列/加表, 不动现有列)
# 运行: QH_DB_PASS=... /opt/quanthedge/venv/bin/python migrate_p27.py
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

DDL = [
    # 用户: 积分余额缓存 + 成长值(永久累加,仅升) + 员工首归因(终身)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS points bigint NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS growth_value bigint NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS staff_code text",
    # 订单: 员工归因(下单时从 user 带入)
    "ALTER TABLE iap_orders ADD COLUMN IF NOT EXISTS staff_code text",
    # 积分流水: 每笔变动一行, 与 users.points 同事务写
    """CREATE TABLE IF NOT EXISTS points_ledger(
        id bigserial PRIMARY KEY,
        user_id bigint NOT NULL,
        delta bigint NOT NULL,
        balance_after bigint NOT NULL,
        reason text NOT NULL,
        ref_type text DEFAULT '',
        ref_id text DEFAULT '',
        operator text DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_points_ledger_user ON points_ledger(user_id, id DESC)",
    # 员工推广码: 一人一码, 无层级(与 agents 三级树隔离)
    """CREATE TABLE IF NOT EXISTS staff(
        code text PRIMARY KEY,
        name text NOT NULL DEFAULT '',
        dept text DEFAULT '',
        username text DEFAULT '',
        default_trial_days int DEFAULT 3,
        default_force_demo boolean DEFAULT true,
        enabled boolean DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_users_staff ON users(staff_code)",
    "CREATE INDEX IF NOT EXISTS ix_orders_staff ON iap_orders(staff_code)",
]

def main():
    if not DB["password"]:
        raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    for s in DDL:
        cur.execute(s)
    # 校验
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name IN ('points','growth_value','staff_code')")
    ucols=sorted(r[0] for r in cur.fetchall())
    cur.execute("SELECT to_regclass('public.points_ledger'), to_regclass('public.staff')")
    tbls=cur.fetchone()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='iap_orders' AND column_name='staff_code'")
    ocol=[r[0] for r in cur.fetchall()]
    c.close()
    print("migrate_p27 done.")
    print("  users 新列:", ucols)
    print("  iap_orders.staff_code:", ocol)
    print("  points_ledger / staff:", tbls)

if __name__=="__main__":
    main()
