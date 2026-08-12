# migrate_p30: 活动引擎 — 声明式活动规则(事件+条件+动作), 运营在 qhadmin 建活动即生效(幂等)
# 全 quanthedge 自有表, 无 postgres 依赖。
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

DDL = [
    # 活动规则: event 触发事件, cond JSON 条件, actions JSON 动作数组, 生效期/优先级/开关
    # category(仅归类展示): trial_convert/retention/agent/staff/recall
    # event: register/trial_activate/first_paid/paid/recharge/checkin/recall_trial/recall_sub
    """CREATE TABLE IF NOT EXISTS campaigns(
        id bigserial PRIMARY KEY,
        name text NOT NULL,
        category text NOT NULL DEFAULT 'retention',
        event text NOT NULL,
        cond jsonb DEFAULT '{}'::jsonb,
        actions jsonb DEFAULT '[]'::jsonb,
        per_user_limit int DEFAULT 1,
        total_limit int DEFAULT 0,
        fired_count int DEFAULT 0,
        priority int DEFAULT 1,
        valid_from timestamptz,
        valid_until timestamptz,
        enabled boolean DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    # 活动发放记录(审计 + 逐用户限次)
    """CREATE TABLE IF NOT EXISTS campaign_grants(
        id bigserial PRIMARY KEY,
        campaign_id bigint NOT NULL,
        username text NOT NULL,
        event text DEFAULT '',
        detail jsonb DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_campgrants_camp ON campaign_grants(campaign_id, username)",
    "CREATE INDEX IF NOT EXISTS ix_campaigns_event ON campaigns(event, enabled)",
]

def main():
    if not DB["password"]: raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    for s in DDL: cur.execute(s)
    cur.execute("SELECT to_regclass('public.campaigns'),to_regclass('public.campaign_grants')")
    print("tables:", cur.fetchone())
    c.close(); print("migrate_p30 done.")

if __name__=="__main__":
    main()
