# migrate_p26: 每模板 1 个专属声音人设(试听文本贴合模板主题) + 通知模板 1:1 配对
# 幂等(sounds ON CONFLICT DO UPDATE; 模板按 name 定位)。保留通用 sweet/mature 供手动广播。
# 运行: QH_DB_PASS=... /opt/quanthedge/venv/bin/python migrate_p26.py
import os, psycopg2
DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))

# 语音: 御姐=zh-CN-XiaoyiNeural(风险,沉稳偏慢略低) / 甜妹=zh-CN-XiaoxiaoNeural(系统营销/交易,元气偏快略高)
YU = "zh-CN-XiaoyiNeural"      # 御姐
TM = "zh-CN-XiaoxiaoNeural"    # 甜妹

# 每条: sound_key, 人设名, persona风格, edge_voice, rate, pitch, 试听文本(贴合模板主题), sort
# key 命名 tpl_<模板语义>, 与模板 1:1
SOUNDS = [
    # ===== 风险类 → 御姐(声调更低更慢, 严重项再压) =====
    ("tpl_singleleg", "单腿告警·御姐", "御姐·风险告警", YU, "-6%",  "-10Hz",
     "警告，检测到单腿暴露，一条腿已成交、另一条腿失败，请立即人工核查处理。", 11),
    ("tpl_naked",     "裸空暴露·御姐", "御姐·高危告警", YU, "-10%", "-14Hz",
     "严重警告，出现裸空暴露，单边持仓未对冲，风险极高，请马上人工介入。", 12),
    ("tpl_stoploss",  "止损建议·御姐", "御姐·风险告警", YU, "-6%",  "-10Hz",
     "止损提示，当前品种已触及止损点位，请确认是否手动平仓。", 13),
    ("tpl_divergence","点差背离·御姐", "御姐·风险告警", YU, "-6%",  "-10Hz",
     "点差背离护栏触发，主对冲点差超出上限，已软暂停开仓。", 14),
    ("tpl_slippage",  "滑点保护·御姐", "御姐·风险告警", YU, "-6%",  "-10Hz",
     "滑点保护触发，当前滑点超出容忍阈值，已暂停下单一段时间。", 15),
    ("tpl_fluct",     "波动带闸·御姐", "御姐·风险告警", YU, "-6%",  "-10Hz",
     "波动带闸触发，市场波动超过设定区间，已暂缓入场。", 16),
    ("tpl_margin",    "保证金预留·御姐", "御姐·高危告警", YU, "-8%", "-12Hz",
     "保证金预留不足，主账户或对冲账户余量偏低，已跳过本次开仓。", 17),
    # ===== 系统/营销/交易 → 甜妹(元气偏快略高; 止盈更欢快) =====
    ("tpl_marketclose","休市提醒·甜妹", "甜妹·系统提醒", TM, "+6%",  "+10Hz",
     "亲，市场即将休市啦，记得留意持仓哦～", 21),
    ("tpl_announce",   "系统公告·甜妹", "甜妹·系统营销", TM, "+8%",  "+12Hz",
     "亲，系统有新的公告啦，记得及时查收哦～", 22),
    ("tpl_takeprofit", "止盈到点·甜妹", "甜妹·喜报", TM, "+10%", "+16Hz",
     "恭喜您，已到止盈点位，成功落袋一笔收益，真棒～", 23),
    ("tpl_entryspread","入场点差偏大·甜妹", "甜妹·交易提示", TM, "+6%", "+10Hz",
     "小提示，当前点差偏大，已超过入场阈值，暂缓入场等更好时机哦。", 24),
    ("tpl_weekendstop","休市停单·甜妹", "甜妹·系统提醒", TM, "+6%",  "+10Hz",
     "亲，进入休市时段啦，自动进出场已暂停，周末好好休息哦～", 25),
    ("tpl_entitle",    "权益降级·甜妹", "甜妹·系统提醒", TM, "+6%",  "+10Hz",
     "温馨提示，您的自动交易权益已失效，已切换为影子模式，续费即可恢复哦～", 26),
    ("tpl_ratelimit",  "API限频·甜妹", "甜妹·系统提醒", TM, "+6%",  "+10Hz",
     "小提示，接口调用接近上限，已自动降频保护，稍等一下就好啦～", 27),
    ("tpl_capacity",   "容量缩减·甜妹", "甜妹·交易提示", TM, "+6%",  "+10Hz",
     "提示，交易容量已缩减，正在撤销多余的在途开仓单哦。", 28),
]

# 模板名 → sound_key (1:1)
MAP = {
    "单腿告警":"tpl_singleleg", "裸空暴露":"tpl_naked", "止损建议":"tpl_stoploss",
    "点差背离护栏":"tpl_divergence", "滑点保护":"tpl_slippage", "波动带闸":"tpl_fluct",
    "保证金预留不足":"tpl_margin",
    "休市提醒":"tpl_marketclose", "系统公告":"tpl_announce", "止盈到点":"tpl_takeprofit",
    "入场点差偏大":"tpl_entryspread", "休市停单":"tpl_weekendstop", "权益失效降级":"tpl_entitle",
    "API限频预警":"tpl_ratelimit", "容量在途撤单":"tpl_capacity",
}

def main():
    if not DB["password"]:
        raise SystemExit("QH_DB_PASS 未设置")
    c=psycopg2.connect(**DB); c.autocommit=False; cur=c.cursor()
    try:
        # 1) upsert 15 专属人设(engine=edge)
        for key,name,persona,voice,rate,pitch,sample,sort in SOUNDS:
            cur.execute("""INSERT INTO notification_sounds
                           (key,name,persona,engine,lang,rate,pitch,voice_hint,edge_voice,edge_rate,edge_pitch,sample_text,enabled,sort,updated_at)
                           VALUES(%s,%s,%s,'edge','zh-CN',1.0,1.0,'',%s,%s,%s,%s,true,%s,now())
                           ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name,persona=EXCLUDED.persona,engine='edge',
                           edge_voice=EXCLUDED.edge_voice,edge_rate=EXCLUDED.edge_rate,edge_pitch=EXCLUDED.edge_pitch,
                           sample_text=EXCLUDED.sample_text,enabled=true,sort=EXCLUDED.sort,updated_at=now()""",
                        (key,name,persona,voice,rate,pitch,sample,sort))
        # 2) 模板 1:1 配对
        miss=[]
        for tname,skey in MAP.items():
            cur.execute("UPDATE notification_templates SET sound_key=%s,updated_at=now() WHERE template_name=%s",(skey,tname))
            if cur.rowcount==0: miss.append(tname)
        if miss:
            raise SystemExit("以下模板名未匹配到(检查是否改名): %s"%miss)
        c.commit()
    except Exception:
        c.rollback(); raise
    # 校验输出
    cur.execute("""SELECT t.id,t.template_name,t.category,t.sound_key,s.name,s.edge_voice
                   FROM notification_templates t LEFT JOIN notification_sounds s ON s.key=t.sound_key ORDER BY t.id""")
    print("=== 模板 1:1 配对结果 ===")
    for r in cur.fetchall():
        print("  #%2d [%s] %-14s -> %s (%s / %s)"%(r[0],r[2],r[1],r[3],r[4],r[5]))
    cur.execute("SELECT count(*) FROM notification_sounds"); print("人设总数:",cur.fetchone()[0])
    c.close()

if __name__=="__main__":
    main()
