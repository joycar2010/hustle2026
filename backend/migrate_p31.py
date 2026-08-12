# migrate_p31: agents 加 owner_username(代理运营用户, 招募奖励/代理活动的积分接收方)。幂等。
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))
def main():
    if not DB["password"]: raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    cur.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS owner_username text")
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='agents' AND column_name='owner_username'")
    print("agents.owner_username:", [r[0] for r in cur.fetchall()])
    c.close(); print("migrate_p31 done.")
if __name__=="__main__":
    main()
