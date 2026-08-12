# migrate_p32: 周期冲榜赛(月度/季度达标赛) — 周期结束按指标排名发奖(幂等)。全 quanthedge 自有表。
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))
DDL = [
    # kind=staff|agent(员工/代理冲榜); period=month|quarter; metric=paid_users|revenue|trials|new_users
    # rewards JSON: [{rank_from,rank_to,type,value}] type: perf(员工绩效分)/points(发owner积分)
    """CREATE TABLE IF NOT EXISTS contests(
        id bigserial PRIMARY KEY,
        name text NOT NULL,
        kind text NOT NULL DEFAULT 'staff',
        period text NOT NULL DEFAULT 'month',
        metric text NOT NULL DEFAULT 'paid_users',
        top_n int DEFAULT 10,
        rewards jsonb DEFAULT '[]'::jsonb,
        enabled boolean DEFAULT true,
        last_settled_period text DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    # 每次结算落榜单(每名一行, 审计 + 前端回看)
    """CREATE TABLE IF NOT EXISTS contest_results(
        id bigserial PRIMARY KEY,
        contest_id bigint NOT NULL,
        period_key text NOT NULL,
        rank int NOT NULL,
        code text NOT NULL,
        name text DEFAULT '',
        metric_value numeric DEFAULT 0,
        reward_type text DEFAULT '',
        reward_value numeric DEFAULT 0,
        reward_to text DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_contestres ON contest_results(contest_id, period_key)",
]
def main():
    if not DB["password"]: raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    for s in DDL: cur.execute(s)
    cur.execute("SELECT to_regclass('public.contests'),to_regclass('public.contest_results')")
    print("tables:", cur.fetchone()); c.close(); print("migrate_p32 done.")
if __name__=="__main__":
    main()
