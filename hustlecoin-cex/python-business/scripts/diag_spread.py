"""诊断 Redis spreads 哈希里某些币种的现货/合约价是否错位。"""
import json
import sys

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")
from app.config import settings  # noqa
import redis  # noqa

r = redis.from_url(settings.redis_url, decode_responses=True)

syms = sys.argv[1:] or ["CRVUSDT", "WLDUSDT", "OPENUSDT", "INJUSDT", "FORMUSDT"]
for s in syms:
    raw = r.hget("spreads", s)
    if not raw:
        print(f"{s}: <none>")
        continue
    d = json.loads(raw)
    sb, sa = d["spot_bid"], d["spot_ask"]
    fb, fa = d["fut_bid"], d["fut_ask"]
    short = str(d["spread_short"])[:7]
    lng = str(d["spread_long"])[:7]
    ts = d.get("ts")
    print(f"{s}: spot[{sb} / {sa}] fut[{fb} / {fa}] short={short} long={lng} ts={ts}")
