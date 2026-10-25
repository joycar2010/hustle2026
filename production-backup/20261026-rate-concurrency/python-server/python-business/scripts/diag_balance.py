"""诊断:子账户余额推送为何空 + 顶栏 worker 计数。"""
import asyncio
import json
import sys

sys.path.insert(0, "/home/ec2-user/hustlecoin-cex/python-business")
from app.config import settings  # noqa
from app.db.session import SessionLocal  # noqa
from app.db.models import SubAccount  # noqa
import redis  # noqa


async def main():
    r = redis.from_url(settings.redis_url, decode_responses=True)
    print("=== redis balance:latest:1 ===")
    raw = r.get("balance:latest:1")
    if raw:
        d = json.loads(raw)
        print("balances count:", len(d.get("balances", [])),
              "pos_count:", d.get("position_count"), "total_contracts:", d.get("total_contracts"))
    else:
        print("balance:latest:1 = <MISSING>")

    print("=== engine:weight:latest (顶栏权重) ===")
    print(r.get("engine:weight:latest"))

    db = SessionLocal()
    subs = db.query(SubAccount).filter(SubAccount.is_enabled == True).all()
    db.close()
    print(f"=== 逐子账户 margin / futures 调用测试({len(subs)} 个启用) ===")
    from engine.trading.binance_trading import BinanceTradingClient
    for acc in subs:
        async with BinanceTradingClient(acc.api_key, acc.api_secret) as c:
            m_ok = f_ok = "?"
            mlevel = navail = None
            try:
                m = await c.get_margin_account()
                m_ok = "OK"
                mlevel = m.get("marginLevel")
            except Exception as e:
                m_ok = f"ERR {str(e)[:60]}"
            try:
                f = await c.get_futures_account()
                f_ok = "OK"
                navail = f.get("availableBalance")
            except Exception as e:
                f_ok = f"ERR {str(e)[:60]}"
            print(f"  #{acc.id} {acc.note}: margin={m_ok}(level={mlevel}) futures={f_ok}(avail={navail})")


asyncio.run(main())
