"""核实 Aerodrome(Base/Solidly)报价:Router.getAmountsOut(amountIn, Route[])。
   Route=(from,to,stable,factory)。用 Alchemy。验证那批"V3 浅池"币在 Aerodrome 有深池。
   CROSSARB_BASE_RPC=<alchemy> python aero_probe.py
"""
import os, json, urllib.request
from web3 import Web3

RPC = os.environ.get("CROSSARB_BASE_RPC", "https://mainnet.base.org")
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"; USDC_DEC = 6
WETH = "0x4200000000000000000000000000000000000006"
ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"   # Aerodrome Router (待核实)
FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"  # Aerodrome PoolFactory (待核实)
NOTIONAL = 2500

TOKENS = [  # (name, addr, dec, binance)
    ("BRETT", "0x532f27101965dd16442E59d40670FaF5eBB142E4", 18, "BRETTUSDT"),
    ("ZORA",  "0x1111111111166b7FE7bd91427724B487980aFc69", 18, "ZORAUSDT"),
    ("KAITO", "0x98d0baa52b2D063E780DE12F615f963Fe8537553", 18, "KAITOUSDT"),
    ("AERO",  "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18, "AEROUSDT"),
]
ROUTER_ABI = [{"inputs":[{"name":"amountIn","type":"uint256"},
    {"components":[{"name":"from","type":"address"},{"name":"to","type":"address"},{"name":"stable","type":"bool"},{"name":"factory","type":"address"}],"name":"routes","type":"tuple[]"}],
    "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
router = w3.eth.contract(address=Web3.to_checksum_address(ROUTER), abi=ROUTER_ABI)
usdc = Web3.to_checksum_address(USDC); weth = Web3.to_checksum_address(WETH); fac = Web3.to_checksum_address(FACTORY)

try:
    bn = {d["symbol"]: float(d["bidPrice"]) for d in json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=10))}
except Exception:
    bn = {}

def quote(routes):
    amts = router.functions.getAmountsOut(NOTIONAL*10**USDC_DEC, routes).call()
    return amts[-1]

def main():
    print(f"block={w3.eth.block_number}  router={ROUTER}\n")
    for name, addr, dec, sym in TOKENS:
        a = Web3.to_checksum_address(addr)
        bnp = bn.get(sym, 0)
        best = None
        # 试:直连(volatile/stable) + 经WETH(volatile)
        trials = [
            ("直连vol", [(usdc, a, False, fac)]),
            ("直连stb", [(usdc, a, True, fac)]),
            ("经WETH",  [(usdc, weth, False, fac), (weth, a, False, fac)]),
        ]
        for label, routes in trials:
            try:
                out = quote(routes)
                if out <= 0: continue
                eff = NOTIONAL/(out/10**dec)
                ratio = eff/bnp if bnp else 0
                if best is None or abs(ratio-1) < abs(best[2]-1):
                    best = (label, eff, ratio)
            except Exception:
                continue
        if best:
            label, eff, ratio = best
            tag = "✅深(eff≈币安)" if 0.9 <= ratio <= 1.12 else f"⚠偏离{ (ratio-1)*100:.0f}%"
            print(f"[{name:6s}] 币安bid={bnp:.6g} | Aerodrome {label} eff={eff:.6g} ratio={ratio:.3f} {tag}")
        else:
            print(f"[{name:6s}] Aerodrome 无可用路由(或Router地址需核实)")

if __name__ == "__main__":
    main()
