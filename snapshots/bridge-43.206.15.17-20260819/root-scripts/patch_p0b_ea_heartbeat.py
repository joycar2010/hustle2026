#!/usr/bin/env python3
"""
P0-B: QHBridge.mq4 heartbeat 补丁生成器
根因: ExportMeta() 被 IsConnected()&&AccountNumber()>0 保护,
      OrderSend 期间终端状态瞬间 false 导致 meta.json 停止写入。
修复: 无条件写 heartbeat.json (只含 ea_alive/ts/build),
      meta.json 写入条件不变但超期后用 heartbeat 判断 EA 存活。
"""

MQ4_PATH = r"D:\MT4LAB\terminals\ic\MQL4\Experts\QHBridge.mq4"

# 读取源码
with open(MQ4_PATH, 'r', encoding='cp1252', errors='replace') as f:
    src = f.read()

# 检查是否已有 ExportHeartbeat
if "ExportHeartbeat" in src:
    print("already patched")
    exit(0)

# 找到 OnTimer 函数后添加 ExportHeartbeat 调用
OLD_ONTIMER = """void OnTimer()
{
   ExportMeta();"""

NEW_ONTIMER = """void OnTimer()
{
   ExportHeartbeat();   // P0-B: 无条件心跳 — meta.json 超期但 EA 存活时不报失联
   ExportMeta();"""

if src.count(OLD_ONTIMER) != 1:
    # 尝试不同格式
    import re
    m = re.search(r'void OnTimer\(\)\s*\{', src)
    if m:
        idx = src.index('\n', m.end())
        OLD_ONTIMER = src[m.start():idx+1]
        NEW_ONTIMER = OLD_ONTIMER.replace(
            'void OnTimer()\n{',
            'void OnTimer()\n{\n   ExportHeartbeat();   // P0-B: 无条件心跳'
        )
        print(f"Found OnTimer at offset {m.start()}, using regex approach")

assert src.count(OLD_ONTIMER) == 1, f"OnTimer anchor: {src.count(OLD_ONTIMER)} matches"

# 找到文件末尾(最后一个}) 前添加 ExportHeartbeat 函数
HEARTBEAT_FUNC = """
//+------------------------------------------------------------------+
//| P0-B: 无条件心跳 — 即使 IsConnected()==false 也写入              |
//| 区分 EA 进程存活 vs MT4 Broker 连接状态                           |
//+------------------------------------------------------------------+
void ExportHeartbeat()
{
   string j = "{";
   j += "\\"ea_alive\\":true";
   j += ",\\"ts\\":" + IntegerToString(TimeCurrent());
   j += ",\\"ea\\":\\"QHBridge/0.10\\"";
   j += ",\\"account\\":" + IntegerToString(AccountNumber());
   j += ",\\"connected\\":" + (IsConnected() ? "true" : "false");
   j += "}";
   WriteState("heartbeat", j);
}
"""

# 在 ExportMeta 函数前插入 ExportHeartbeat
OLD_EXPORT_META_DECL = "void ExportMeta()"
NEW_EXPORT_META_DECL = HEARTBEAT_FUNC + "\nvoid ExportMeta()"

assert src.count(OLD_EXPORT_META_DECL) == 1
src = src.replace(OLD_EXPORT_META_DECL, NEW_EXPORT_META_DECL, 1)
src = src.replace(OLD_ONTIMER, NEW_ONTIMER, 1)

with open(MQ4_PATH, 'w', encoding='cp1252', errors='replace') as f:
    f.write(src)

print("OK QHBridge.mq4 heartbeat patch applied")
print("  Added: ExportHeartbeat() - writes heartbeat.json unconditionally")
print("  OnTimer: calls ExportHeartbeat() before ExportMeta()")
print("  Next: recompile .mq4 -> .ex4 (need MT4 terminal with EA editor)")
