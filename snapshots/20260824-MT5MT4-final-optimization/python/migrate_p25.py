# migrate_p25: notification_sounds 增 edge-tts 引擎字段 + 甜妹/御姐 改用微软神经语音
# 幂等。运行: QH_DB_PASS=... /opt/quanthedge/venv/bin/python migrate_p25.py
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

DDL = """
ALTER TABLE notification_sounds ADD COLUMN IF NOT EXISTS engine      text DEFAULT 'browser';
ALTER TABLE notification_sounds ADD COLUMN IF NOT EXISTS edge_voice  text DEFAULT '';
ALTER TABLE notification_sounds ADD COLUMN IF NOT EXISTS edge_rate   text DEFAULT '+0%';
ALTER TABLE notification_sounds ADD COLUMN IF NOT EXISTS edge_pitch  text DEFAULT '+0Hz';
"""

# 甜妹=Xiaoxiao(元气偏快略高) / 御姐=Xiaoyi(沉稳偏慢略低); 均 edge 引擎真中文神经语音
UPDATES = [
    # key, engine, edge_voice, edge_rate, edge_pitch, sample_text
    ("sweet",  "edge", "zh-CN-XiaoxiaoNeural", "+8%",  "+12Hz",
     "亲，系统有新的公告啦，记得及时查收哦～"),
    ("mature", "edge", "zh-CN-XiaoyiNeural",   "-6%",  "-10Hz",
     "警告，检测到单腿暴露风险，请立即人工核查处理。"),
]

def main():
    if not DB["password"]:
        raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=True; cur=c.cursor()
    for stmt in DDL.strip().split("\n"):
        if stmt.strip(): cur.execute(stmt)
    for key,engine,voice,rate,pitch,sample in UPDATES:
        cur.execute("""UPDATE notification_sounds
                       SET engine=%s, edge_voice=%s, edge_rate=%s, edge_pitch=%s, sample_text=%s, updated_at=now()
                       WHERE key=%s""",
                    (engine,voice,rate,pitch,sample,key))
    cur.execute("SELECT key,name,engine,edge_voice,edge_rate,edge_pitch FROM notification_sounds ORDER BY sort,key")
    print("migrate_p25 done. sounds:")
    for r in cur.fetchall(): print("  ",r)
    c.close()

if __name__=="__main__":
    main()
