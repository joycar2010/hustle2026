"""跨新链发现(Optimism/Avalanche/Polygon/Sonic):KyberSwap各链slug+稳定币,
   对候选标的报价,eff≈币安价=深;校验币安有USDT永续。python discover_newchains.py
"""
import json, time, urllib.request
HDR = {"accept": "application/json", "User-Agent": "crossarb/1.0", "x-client-id": "crossarb"}

# 链: slug, 稳定币地址, 稳定币精度
CHAINS = {
    "OP":  ("optimism",  "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85", 6),   # USDC(原生)
    "AVAX":("avalanche", "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E", 6),   # USDC(原生)
    "POLY":("polygon",   "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),   # USDC(原生)
    "SONIC":("sonic",    "0x29219dd400f2Bf60E5a23d13Be72B486D4038894", 6),   # USDC.e
}
# (链, 名称, 代币地址, 精度, 币安USDT永续)
CANDS = [
    # Optimism
    ("OP","ETH","0x4200000000000000000000000000000000000006",18,"ETHUSDT"),
    ("OP","OP","0x4200000000000000000000000000000000000042",18,"OPUSDT"),
    ("OP","WBTC","0x68f180fcCe6836688e9084f035309E29Bf0A2095",8,"BTCUSDT"),
    ("OP","VELO","0x9560e827aF36c94D2Ac33a39bCE1Fe78631088Db",18,"VELODROMEUSDT"),
    # Avalanche
    ("AVAX","AVAX","0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",18,"AVAXUSDT"),
    ("AVAX","WETH","0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB",18,"ETHUSDT"),
    ("AVAX","BTC","0x152b9d0FdC40C096757F570A51E494bd4b943E50",8,"BTCUSDT"),
    ("AVAX","JOE","0x6e84a6216eA6dACC71eE8E6b0a5B7322EEbC0fDd",18,"JOEUSDT"),
    # Polygon
    ("POLY","POL","0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",18,"POLUSDT"),
    ("POLY","WETH","0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",18,"ETHUSDT"),
    ("POLY","WBTC","0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6",8,"BTCUSDT"),
    # Sonic
    ("SONIC","S","0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38",18,"SUSDT"),
    ("SONIC","WETH","0x50c42dEAcD8Fc9773493ED674b675bE577f2634b",18,"ETHUSDT"),
]

def kyber(slug, tin, tout, amt):
    u = f"https://aggregator-api.kyberswap.com/{slug}/api/v1/routes?tokenIn={tin}&tokenOut={tout}&amountIn={amt}"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=12))
    if d.get("code") != 0:
        raise RuntimeError(d.get("message"))
    return d.get("data", {}).get("routeSummary", {})

def main():
    BN = {x["symbol"]: float(x["bidPrice"]) for x in json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=10))}
    keep=[]
    for chain,name,addr,dec,sym in CANDS:
        slug,stable,sdec=CHAINS[chain]; bnp=BN.get(sym,0)
        if bnp<=0:
            print(f"[{chain}:{name:5s}] 币安无 {sym} ❌"); continue
        try:
            rs=kyber(slug,stable,addr,2500*10**sdec); out=int(rs.get("amountOut",0))
            if out<=0: print(f"[{chain}:{name:5s}] kyber无路由 ❌"); time.sleep(0.25); continue
            eff=2500/(out/10**dec); ratio=eff/bnp; gas=rs.get("gasUsd","?")
            deep=0.90<=ratio<=1.12
            print(f"[{chain}:{name:5s}] {sym:10s} 币安={bnp:.5g} eff={eff:.5g} ratio={ratio:.3f} gas=${gas} {'✅' if deep else '✗浅'}")
            if deep: keep.append((chain,name,addr,dec,sym))
            time.sleep(0.25)
        except Exception as e:
            print(f"[{chain}:{name:5s}] ERR {str(e)[:50]}"); time.sleep(0.5)
    print("\n=== 可纳入 ===")
    for k in keep: print("  ",k)

if __name__=="__main__":
    main()
