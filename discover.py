"""跨源深度发现:每个候选币在 {UniV3, Aerodrome V2, Slipstream CL} × {直连USDC, 经WETH}
   × {$2500,$500} 全跑,找 eff≈币安价(=有足够深度)的最佳源。输出可纳入清单。
   CROSSARB_BASE_RPC=<alchemy> python discover.py
"""
import os, json, urllib.request
from web3 import Web3

RPC = os.environ.get("CROSSARB_BASE_RPC", "https://mainnet.base.org")
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"; USDC_DEC = 6
WETH = "0x4200000000000000000000000000000000000006"

UNIV3_QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
AERO_ROUTER  = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERO_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
SLIP_QUOTER  = "0x254cf9e1e6e233aa1ac962cb9b05b2cfeaae15b0"

UNIV3_FEES = [500, 3000, 10000, 100]
SLIP_TS    = [100, 200, 2000, 50, 1]

TOKENS = [  # (name, addr, dec, binance)
    ("BRETT", "0x532f27101965dd16442E59d40670FaF5eBB142E4", 18, "BRETTUSDT"),
    ("ZORA",  "0x1111111111166b7FE7bd91427724B487980aFc69", 18, "ZORAUSDT"),
    ("KAITO", "0x98d0baa52b2D063E780DE12F615f963Fe8537553", 18, "KAITOUSDT"),
    ("ZRO",   "0x6985884C4392D348587B19cb9eAAf157F13271cd", 18, "ZROUSDT"),
    ("TOSHI", "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4", 18, "TOSHIUSDT"),
    ("MORPHO","0xBAa5CC21fd487B8Fcc2F632f3F4E8D37262a0842", 18, "MORPHOUSDT"),
    ("AERO",  "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18, "AEROUSDT"),
    ("AIXBT", "0x4F9Fd6Be4a90f2620860d680c0d4d5Fb53d1A825", 18, "AIXBTUSDT"),
]

QV2 = lambda key: [{"inputs":[{"components":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"amountIn","type":"uint256"},{"name":key,"type":"int24" if key=="tickSpacing" else "uint24"},{"name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"name":"amountOut","type":"uint256"},{"name":"a","type":"uint160"},{"name":"b","type":"uint32"},{"name":"c","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]
ROUTER_ABI = [{"inputs":[{"name":"amountIn","type":"uint256"},{"components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}],"name":"routes","type":"tuple[]"}],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
cs = Web3.to_checksum_address
uquoter = w3.eth.contract(address=cs(UNIV3_QUOTER), abi=QV2("fee"))
squoter = w3.eth.contract(address=cs(SLIP_QUOTER), abi=QV2("tickSpacing"))
router  = w3.eth.contract(address=cs(AERO_ROUTER), abi=ROUTER_ABI)
usdc, weth, afac = cs(USDC), cs(WETH), cs(AERO_FACTORY)

try:
    BN = {d["symbol"]: float(d["bidPrice"]) for d in json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=10))}
except Exception:
    BN = {}

def univ3(tin, tout, amt):
    best = 0
    for fee in UNIV3_FEES:
        try:
            o = uquoter.functions.quoteExactInputSingle((cs(tin), cs(tout), amt, fee, 0)).call()[0]
            best = max(best, o)
        except Exception: pass
    return best

def slip(tin, tout, amt):
    best = 0
    for ts in SLIP_TS:
        try:
            o = squoter.functions.quoteExactInputSingle((cs(tin), cs(tout), amt, ts, 0)).call()[0]
            best = max(best, o)
        except Exception: pass
    return best

def aerov2(tin, tout, amt):
    best = 0
    for stable in (False, True):
        try:
            o = router.functions.getAmountsOut(amt, [(cs(tin), cs(tout), stable, afac)]).call()[-1]
            best = max(best, o)
        except Exception: pass
    return best

def best_eff(addr, dec, notional):
    """返回 (eff, label) 最优,跨三源 × 直连/经WETH。"""
    amt = notional * 10**USDC_DEC
    cands = []
    # 直连 USDC -> token
    for fn, lab in ((univ3, "U3直"), (slip, "CL直"), (aerov2, "V2直")):
        o = fn(usdc, addr, amt)
        if o > 0: cands.append((notional/(o/10**dec), lab))
    # 经 WETH:先 USDC->WETH(UniV3 深),再 WETH->token 各源
    weth_out = univ3(usdc, weth, amt)
    if weth_out > 0:
        for fn, lab in ((univ3, "U3·W"), (slip, "CL·W"), (aerov2, "V2·W")):
            o = fn(weth, addr, weth_out)
            if o > 0: cands.append((notional/(o/10**dec), lab))
    if not cands: return None, None
    # 取 eff 最小(最优可成交价)
    eff, lab = min(cands, key=lambda x: x[0])
    return eff, lab

def main():
    print(f"block={w3.eth.block_number}\n候选 × 源(直/经WETH) × 规模;ratio=eff/币安价,≈1=深\n")
    keep = []
    for name, addr, dec, sym in TOKENS:
        bnp = BN.get(sym, 0)
        row = f"[{name:6s}] 币安={bnp:.6g} "
        deep_at = None
        for notional in (2500, 500):
            eff, lab = best_eff(cs(addr), dec, notional)
            if eff and bnp:
                r = eff/bnp
                ok = 0.90 <= r <= 1.12
                row += f"| ${notional}: {lab} ratio={r:.3f}{'✅' if ok else '✗'} "
                if ok and deep_at is None:
                    deep_at = (notional, lab, r)
            else:
                row += f"| ${notional}: 无路由 "
        print(row)
        if deep_at:
            keep.append((name, addr, dec, sym, deep_at))
    print("\n=== 有足够深度可纳入 ===")
    for k in keep:
        print("  ", k[0], "规模$"+str(k[4][0]), "源="+k[4][1], "ratio="+f"{k[4][2]:.3f}")
    if not keep:
        print("  (无)——这批币在 Base 三大源都没有 $500+ 深度,诚实结论:不纳入")

if __name__ == "__main__":
    main()
