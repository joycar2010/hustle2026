# migrate_p29: 第三阶段 — 积分抵现列 + 好友邀请 + 员工绩效积分(幂等)
# 命门: iap_orders 属主 postgres → 加列须 sudo -u postgres(见部署脚本); 本脚本只建 quanthedge 自有表/列。
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

DDL = [
    # users: 邀请人(首归因终身, 与代理/员工并行)
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS inviter text",
    # 好友邀请关系 + 奖励发放记录(防重复发首付返)
    """CREATE TABLE IF NOT EXISTS invites(
        id bigserial PRIMARY KEY,
        inviter text NOT NULL,
        invitee text NOT NULL,
        stage text NOT NULL DEFAULT 'registered',
        reward_trial_done boolean DEFAULT false,
        reward_paid_done boolean DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_invites_invitee ON invites(invitee)",
    "CREATE INDEX IF NOT EXISTS ix_invites_inviter ON invites(inviter)",
    # 员工绩效积分(与用户对冲积分完全隔离; 内部激励)
    """CREATE TABLE IF NOT EXISTS staff_perf_ledger(
        id bigserial PRIMARY KEY,
        staff_code text NOT NULL,
        delta bigint NOT NULL,
        balance_after bigint NOT NULL,
        reason text NOT NULL,
        ref_type text DEFAULT '',
        ref_id text DEFAULT '',
        operator text DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_staffperf_code ON staff_perf_ledger(staff_code, id DESC)",
    "ALTER TABLE staff ADD COLUMN IF NOT EXISTS perf_points bigint NOT NULL DEFAULT 0",
]

def main():
    if not DB["password"]: raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    for s in DDL: cur.execute(s)
    cur.execute("SELECT to_regclass('public.invites'),to_regclass('public.staff_perf_ledger')")
    print("tables:", cur.fetchone())
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='inviter'")
    print("users.inviter:", [r[0] for r in cur.fetchall()])
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='staff' AND column_name='perf_points'")
    print("staff.perf_points:", [r[0] for r in cur.fetchall()])
    c.close(); print("migrate_p29 done (iap_orders points 列须 sudo postgres 另加)。")

if __name__=="__main__":
    main()
