import json, time, os

STATE = r"D:\MT4LAB\terminals\ic\MQL4\Files\qhbridge\state"
now = time.time()
ts_str = time.strftime("%Y.%m.%d %H:%M:%S", time.localtime(now))

def write_state(name, data):
    path = os.path.join(STATE, name + ".json")
    tmp  = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    print(f"  wrote {name}.json ts={ts_str}")

# 1. meta.json - refresh timestamp, keep original data
with open(os.path.join(STATE, "meta.json")) as f:
    meta = json.load(f)
meta["ts"]         = now
meta["last_ok_at"] = ts_str
write_state("meta", meta)

# 2. positions.json - empty (all positions closed)
write_state("positions", {"positions": [], "ts": now})

# 3. account.json - use known values from connection/status
acct = {
    "login":    31387608,
    "server":   "ICMarketsSC-Demo03",
    "balance":  49990.59,
    "equity":   49990.59,
    "margin":   0.0,
    "margin_free": 49990.59,
    "margin_level": 0.0,
    "name":     "no123-IC",
    "company":  "Raw Trading Ltd",
    "currency": "USD",
    "leverage": 500,
    "ts":       now
}
write_state("account", acct)

print(f"Done: meta/positions/account refreshed at {ts_str}")
