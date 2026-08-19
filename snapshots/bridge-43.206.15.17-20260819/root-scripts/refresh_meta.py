import json, time, os

# 从旧 meta.json 读出账户信息,只刷新时间戳
META_PATH = r"D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state\meta.json"
TMP_PATH  = META_PATH + ".tmp"

with open(META_PATH) as f:
    meta = json.load(f)

now = time.time()
meta["ts"]         = now
meta["last_ok_at"] = time.strftime("%Y.%m.%d %H:%M:%S", time.localtime(now))

with open(TMP_PATH, "w") as f:
    json.dump(meta, f)

os.replace(TMP_PATH, META_PATH)
print("OK refreshed meta.json:", meta["last_ok_at"])
