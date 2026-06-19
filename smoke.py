"""一次性烟雾测试(多市场):跑一拍完整采集并打印每个市场的算账。
    python smoke.py
"""
from app.binance_feed import BinanceFutFeed
from app.config import cfg
from app.dex_quoter import Quoter
from app.markets import load_markets
from app.spread_calc import compute_spread
import time


def main():
    markets = load_markets()
    print(f"[cfg] RPC={cfg.base_rpc}  notional=${cfg.notional_usd}  min_net={cfg.min_net_bps}bps  "
          f"markets={[m.key for m in markets]}")

    q = Quoter(cfg.base_rpc)
    print(f"[chain] connected={q.connected()}  block={q.block_number()}")

    eth_usd = q.eth_usd_price()
    gas_price = q.gas_price_wei()
    l2_eth = cfg.gas_units * gas_price / 1e18
    try:
        l1_eth = q.l1_fee_wei() / 1e18
        src = "实时oracle"
    except Exception as e:
        l1_eth = cfg.l1_fee_usd / eth_usd
        src = f"回退固定(oracle失败:{e})"
    gas_usd = (l2_eth + l1_eth) * eth_usd
    print(f"[gas]  ETH/USD={eth_usd:.2f}  L2={l2_eth*eth_usd:.5f}$  L1={l1_eth*eth_usd:.5f}$({src})  "
          f"=> 每swap gas_usd={gas_usd:.5f}$")

    tickers = BinanceFutFeed(cfg.binance_fapi).all_book_tickers()
    print(f"[cex]  币安 bookTicker 一次拉全:{len(tickers)} 个symbol")
    print("-" * 96)

    ts = int(time.time() * 1000)
    for m in markets:
        sym = m.binance_symbol
        if sym not in tickers:
            print(f"[{m.key}] 币安无 {sym} 行情,跳过"); continue
        try:
            quote = q.quote_buy(m, m.notional_usd or cfg.notional_usd)
        except Exception as e:
            print(f"[{m.key}] DEX报价失败: {type(e).__name__} {e}"); continue
        t = tickers[sym]
        r = compute_spread(
            market=m.key, binance_symbol=sym, ts=ts,
            dex_eff_price=quote.eff_price, dex_mid_price=quote.mid_price,
            base_out=quote.base_out, slippage_bps=quote.slippage_bps,
            gas_usd=gas_usd, fut_bid=t["bid"], fut_ask=t["ask"],
            notional_usd=m.notional_usd or cfg.notional_usd,
            taker_fee_bps=cfg.taker_fee_bps, recycle_bps=cfg.recycle_bps,
            min_net_bps=cfg.min_net_bps,
        )
        print(f"[{m.key:13s}] DEX有效价={r.dex_eff_price:>12.4f} 中间价={r.dex_mid_price:>12.4f} "
              f"币安bid={r.fut_bid:>12.4f} 滑点={r.slippage_bps:5.2f}bps")
        print(f"               gross={r.gross_bps:7.2f}  入场净={r.net_entry_bps:7.2f}  "
              f"往返净={r.net_bps:7.2f}bps  机会={'✓' if r.is_opportunity else '·'} (阈值{cfg.min_net_bps})")
    print("-" * 96)
    print("单点为负正常;P0 看的是影子运行数周后【各市场机会的频率与规模】。波动大/低效的标的(如VIRTUAL)更可能出现错位。")


if __name__ == "__main__":
    main()
