"""跨链发现(KyberSwap 各链 slug,免RPC):对每个 (链,标的) 用聚合器报价,
   eff≈币安价=有足够深度;并校验币安有该 USDT 永续。输出可纳入清单。
   python discover_kyber.py
"""
import json, time, urllib.request, urllib.error

HDR = {"accept": "application/json", "User-Agent": "crossarb/1.0", "x-client-id": "crossarb"}

# 链: slug, 稳定币地址, 稳定币精度
CHAINS = {
    "ETH": ("ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),   # USDC
    "BSC": ("bsc",      "0x55d398326f99059fF775485246999027B3197955", 18),  # USDT(BSC 18位)
    "ARB": ("arbitrum", "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),   # USDC(Arb 原生)
}

# (链, 名称, 代币地址, 精度, 币安USDT永续, 试单名义额)
CANDS = [
    # Ethereum
    ("ETH", "ETH",  "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18, "ETHUSDT", 2500),
    ("ETH", "WBTC", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8,  "BTCUSDT", 2500),
    ("ETH", "LINK", "0x514910771AF9Ca656af840dff83E8264EcF986CA", 18, "LINKUSDT", 2500),
    ("ETH", "UNI",  "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18, "UNIUSDT", 2500),
    ("ETH", "PEPE", "0x6982508145454Ce325dDbE47a25d4ec3d2311933", 18, "PEPEUSDT", 2500),
    # BSC (USDT 计价)
    ("BSC", "BNB",  "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", 18, "BNBUSDT", 2500),
    ("BSC", "CAKE", "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82", 18, "CAKEUSDT", 2500),
    # Arbitrum
    ("ARB", "ARB",  "0x912CE59144191C1204E64559FE8253a0e49E6548", 18, "ARBUSDT", 2500),
    ("ARB", "WETH", "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", 18, "ETHUSDT", 2500),
    ("ARB", "WBTC", "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f", 8,  "BTCUSDT", 2500),
    ("ARB", "GMX",  "0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a", 18, "GMXUSDT", 2500),
    ("ARB", "LINK", "0xf97f4df75117a78c1A5a0DBb814Af92458539FB4", 18, "LINKUSDT", 2500),
    ("ARB", "PENDLE","0x808507121B80c02388fAd14726482e061B8da827",18, "PENDLEUSDT", 2500),
]


def kyber(slug, tin, tout, amt):
    u = f"https://aggregator-api.kyberswap.com/{slug}/api/v1/routes?tokenIn={tin}&tokenOut={tout}&amountIn={amt}"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=12))
    if d.get("code") != 0:
        raise RuntimeError(d.get("message"))
    return d.get("data", {}).get("routeSummary", {})


def main():
    BN = {x["symbol"]: float(x["bidPrice"]) for x in json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=10))}
    keep = []
    for chain, name, addr, dec, sym, notional in CANDS:
        slug, stable, sdec = CHAINS[chain]
        bnp = BN.get(sym, 0)
        if bnp <= 0:
            print(f"[{chain}:{name:6s}] 币安无 {sym} ❌"); continue
        try:
            rs = kyber(slug, stable, addr, notional * 10 ** sdec)
            out = int(rs.get("amountOut", 0))
            if out <= 0:
                print(f"[{chain}:{name:6s}] kyber 无路由 ❌"); time.sleep(0.25); continue
            eff = notional / (out / 10 ** dec)
            ratio = eff / bnp
            gas = rs.get("gasUsd", "?")
            deep = 0.90 <= ratio <= 1.12
            print(f"[{chain}:{name:6s}] {sym:10s} 币安={bnp:.6g} eff={eff:.6g} ratio={ratio:.3f} gas=${gas} {'✅' if deep else '✗浅'}")
            if deep:
                keep.append((chain, name, addr, dec, sym))
            time.sleep(0.25)
        except Exception as e:
            print(f"[{chain}:{name:6s}] ERR {e}"); time.sleep(0.5)
    print("\n=== 可纳入 ===")
    for k in keep:
        print("  ", k)


if __name__ == "__main__":
    main()
