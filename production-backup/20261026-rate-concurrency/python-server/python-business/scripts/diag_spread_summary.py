"""汇总 spreads 哈希的背离/新鲜度分布。"""
import json
import time
import sys

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")
from app.config import settings  # noqa
import redis  # noqa

r = redis.from_url(settings.redis_url, decode_responses=True)
now = int(time.time() * 1000)
rows = []
for k, v in r.hgetall("spreads").items():
    d = json.loads(v)
    age = (now - d["ts"]) / 1000.0
    sm = (float(d["spot_bid"]) + float(d["spot_ask"])) / 2
    fm = (float(d["fut_bid"]) + float(d["fut_ask"])) / 2
    div = abs(sm - fm) / fm * 100 if fm else 999
    rows.append((div, age, k))
rows.sort(reverse=True)
total = len(rows)
bad = sum(1 for d, a, k in rows if d > 3)
old = sum(1 for d, a, k in rows if a > 30)
print("total=%d  div>3%%=%d  age>30s=%d" % (total, bad, old))
print("背离 top5:")
for d, a, k in rows[:5]:
    print("  %-12s div=%6.2f%% age=%6.1fs" % (k, d, a))
