# migrate_p28: 第二阶段 — 折扣券 + 员工阶梯提成配置(幂等, 纯加表/加列)
# 运行: QH_DB_PASS=... /opt/quanthedge/venv/bin/python migrate_p28.py
# 注意: coupons/coupon_redemptions 属主 quanthedge(本脚本建); staff 属主 quanthedge(p27建, 可 ALTER)
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

DDL = [
    # 折扣券: kind=percent(value=折扣百分比0-100) / fixed(value=立减USDT)
    # applies_to=subscription/iap/any; target_username 非空=专属券(仅该用户可用), 空=通用活动券
    """CREATE TABLE IF NOT EXISTS coupons(
        code text PRIMARY KEY,
        name text NOT NULL DEFAULT '',
        kind text NOT NULL DEFAULT 'percent',
        value numeric NOT NULL DEFAULT 0,
        applies_to text NOT NULL DEFAULT 'any',
        min_amount numeric DEFAULT 0,
        max_discount numeric DEFAULT 0,
        total_qty int DEFAULT 0,
        used_qty int DEFAULT 0,
        per_user_limit int DEFAULT 1,
        target_username text,
        valid_from timestamptz,
        valid_until timestamptz,
        enabled boolean DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    # 券核销记录: 每次成功使用一行(全局用量 + 逐用户次数 + 审计)
    """CREATE TABLE IF NOT EXISTS coupon_redemptions(
        id bigserial PRIMARY KEY,
        code text NOT NULL,
        user_id bigint NOT NULL,
        order_id bigint,
        discount numeric NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_couponred_code ON coupon_redemptions(code)",
    "CREATE INDEX IF NOT EXISTS ix_couponred_user ON coupon_redemptions(user_id, code)",
    # 员工阶梯提成配置: 每有效试用固定额 + 首单比例 + 复购比例(走薪资, 此处只配+算, 不建钱包)
    "ALTER TABLE staff ADD COLUMN IF NOT EXISTS comm_trial numeric DEFAULT 0",
    "ALTER TABLE staff ADD COLUMN IF NOT EXISTS comm_first_rate numeric DEFAULT 0",
    "ALTER TABLE staff ADD COLUMN IF NOT EXISTS comm_repeat_rate numeric DEFAULT 0",
]

def main():
    if not DB["password"]: raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    for s in DDL: cur.execute(s)
    cur.execute("SELECT to_regclass('public.coupons'),to_regclass('public.coupon_redemptions')")
    print("tables:", cur.fetchone())
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='staff' AND column_name LIKE 'comm%%'")
    print("staff comm cols:", sorted(r[0] for r in cur.fetchall()))
    c.close(); print("migrate_p28 done.")

if __name__=="__main__":
    main()
