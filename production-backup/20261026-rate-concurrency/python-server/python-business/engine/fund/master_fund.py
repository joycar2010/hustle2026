"""主账户(hedge_via_master)资金纳管:对主账户也执行 BNB 维护 / USDT 欠款还款 / 小额兑换。

背景:BNB 抵扣、BNB/USDT 欠款还款、小额兑换原本只在各子账户 worker 里跑,主账户(持全部合约
对冲腿、付合约手续费、常驻 BNB 抵扣需求)无人纳管 → UI「全仓」名不副实。本模块补齐主账户那一份。

并发去重:5 个子账户 worker 共享同一主账户,故用 Redis 锁 `engine:masterfund:{user_id}`
(SET NX EX=interval)保证每用户每周期只有一个 worker 真正执行,其余直接跳过。
"""
import logging

from engine.fund.bnb_manager import run_bnb_check
from engine.fund.debt_repayer import run_usdt_debt_check
from engine.trading.master_client import get_master_futures_client

logger = logging.getLogger(__name__)

MASTER_NOTE = "主账户"


async def run_master_fund_check(user_id, redis, fund_rules, global_rules, notifier, *, ttl_sec: int):
    """对主账户执行一轮资金维护。Redis 锁去重:每 user 每 ttl_sec 只跑一次。"""
    lock_key = f"engine:masterfund:{user_id or 0}"
    try:
        # NX+EX:抢到锁(返回真)才执行;TTL=周期,自动过期允许下周期再抢
        got = await redis.set(lock_key, "1", nx=True, ex=max(int(ttl_sec), 60))
        if not got:
            return  # 别的 worker 本周期已处理主账户
    except Exception as e:
        logger.debug(f"masterfund lock failed (user={user_id}): {e}")
        return

    master = await get_master_futures_client(user_id)
    if master is None:
        logger.debug(f"masterfund: master client unavailable (user={user_id})")
        return

    # 复用子账户同款维护逻辑,client 换成主账户:
    # run_bnb_check 内含 BNB抵扣下发 + 低额补买 + BNB欠款(买入补足)还款 + dust→BNB
    try:
        await run_bnb_check(
            master, fund_rules, notifier, MASTER_NOTE,
            bnb_burn_enabled=getattr(global_rules, "bnb_burn_enabled", None),
        )
    except Exception as e:
        logger.warning(f"masterfund bnb_check failed (user={user_id}): {e}")

    # USDT 欠款还款(主账户跨保证金若有欠款则还;纯期货户无欠款时 no-op,无害)
    try:
        await run_usdt_debt_check(master, fund_rules, notifier, MASTER_NOTE)
    except Exception as e:
        logger.warning(f"masterfund usdt_debt failed (user={user_id}): {e}")
