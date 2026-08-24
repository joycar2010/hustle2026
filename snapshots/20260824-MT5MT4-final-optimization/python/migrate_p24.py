# migrate_p24: notification_sounds 管理表(TTS 人设调参) + 清除 basic 测试 plan
# 幂等: 可重复执行。运行: QH_DB_PASS=... /opt/quanthedge/venv/bin/python migrate_p24.py
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

DDL = """
CREATE TABLE IF NOT EXISTS notification_sounds(
  key         text PRIMARY KEY,
  name        text NOT NULL,
  persona     text DEFAULT '',
  lang        text DEFAULT 'zh-CN',
  rate        double precision DEFAULT 1.0,
  pitch       double precision DEFAULT 1.0,
  voice_hint  text DEFAULT '',
  sample_text text DEFAULT '',
  enabled     boolean DEFAULT true,
  sort        integer DEFAULT 0,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);
"""

# 甜妹/御姐 两个自带人设(浏览器 TTS 调参: 甜妹=高音调稍快, 御姐=低音调稍慢)
SEED = [
    # key, name, persona, lang, rate, pitch, voice_hint, sample_text, sort
    ("sweet",  "甜妹", "甜美/元气", "zh-CN", 1.08, 1.28, "Xiaoxiao|Ting|Yaoyao|female|女", "主人，有新的行情提醒啦～", 1),
    ("mature", "御姐", "成熟/沉稳", "zh-CN", 0.94, 0.82, "Xiaoyi|Huihui|Yunxi|female|女", "您有一条重要的交易通知，请注意查收。", 2),
]

def main():
    if not DB["password"]:
        raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    cur.execute(DDL)
    for k,name,persona,lang,rate,pitch,hint,sample,sort in SEED:
        cur.execute("""INSERT INTO notification_sounds(key,name,persona,lang,rate,pitch,voice_hint,sample_text,enabled,sort)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,true,%s)
                       ON CONFLICT (key) DO NOTHING""",
                    (k,name,persona,lang,rate,pitch,hint,sample,sort))
    # 清除 basic 测试 plan(免费用户以 plan=NULL 表示, 无套餐)
    cur.execute("UPDATE users SET plan=NULL WHERE plan='basic'")
    n=cur.rowcount
    cur.execute("SELECT count(*) FROM notification_sounds"); sc=cur.fetchone()[0]
    c.close()
    print("migrate_p24 done: notification_sounds rows=%d, cleared basic plan rows=%d" % (sc, n))

if __name__=="__main__":
    main()
