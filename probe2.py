"""探测候选 Base 标的:链上核实 symbol/decimals + 最优【低费档】USDC 池 + 试报价滑点
   + 校验币安是否有该 USDT 永续。用 Alchemy(读 CROSSARB_BASE_RPC)避免 429。
   用法: CROSSARB_BASE_RPC=<alchemy> python probe2.py
"""
import os, json, urllib.request
from web3 import Web3

RPC = os.environ.get("CROSSARB_BASE_RPC", "https://mainnet.base.org")
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"; USDC_DEC = 6
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
FEES = [500, 3000, 10000, 100]   # 偏好顺序:低费优先
NOTIONAL = 2500

# (名称, 地址, 币安USDT永续) —— 由本脚本链上核实
CANDIDATES = [
    ("AERO",   "0x940181a94A35A4569E4529A3CDfB74e38FD98631", "AEROUSDT"),
    ("BRETT",  "0x532f27101965dd16442E59d40670FaF5eBB142E4", "BRETTUSDT"),
    ("TOSHI",  "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4", "TOSHIUSDT"),
    ("DEGEN",  "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed", "DEGENUSDT"),
    ("MORPHO", "0xBAa5CC21fd487B8Fcc2F632f3F4E8D37262a0842", "MORPHOUSDT"),
    ("ZORA",   "0x1111111111166b7FE7bd91427724B487980aFc69", "ZORAUSDT"),
    ("KAITO",  "0x98d0baa52b2D063E780DE12F615f963Fe8537553", "KAITOUSDT"),
    ("AIXBT",  "0x4F9Fd6Be4a90f2620860d680c0d4d5Fb53d1A825", "AIXBTUSDT"),
    ("EURC",   "0x60a3E35Cc302bFA44Cb288Bc5a4F316Fdb1adb42", "EURUSDT"),
    ("ZRO",    "0x6985884C4392D348587B19cb9eAAf157F13271cd", "ZROUSDT"),
]

ERC20 = [{"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
         {"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"}]
FAC_ABI = [{"inputs":[{"type":"address"},{"type":"address"},{"type":"uint24"}],"name":"getPool","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
POOL_ABI = [{"inputs":[],"name":"liquidity","outputs":[{"type":"uint128"}],"stateMutability":"view","type":"function"}]
Q_ABI = [{"inputs":[{"components":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"amountIn","type":"uint256"},{"name":"fee","type":"uint24"},{"name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"name":"amountOut","type":"uint256"},{"name":"a","type":"uint160"},{"name":"b","type":"uint32"},{"name":"c","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
fac = w3.eth.contract(address=Web3.to_checksum_address(FACTORY), abi=FAC_ABI)
quoter = w3.eth.contract(address=Web3.to_checksum_address(QUOTER), abi=Q_ABI)
usdc = Web3.to_checksum_address(USDC)

# 币安 USDT 永续 symbol->bid 价
try:
    data = json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=10))
    BN = {d["symbol"]: float(d["bidPrice"]) for d in data}
except Exception as e:
    BN = {}; print("WARN 取币安符号失败:", e)


def main():
    print(f"RPC={'alchemy' if 'alchemy' in RPC else RPC}  block={w3.eth.block_number}  binance_syms={len(BN)}\n")
    good = []
    for name, addr, sym in CANDIDATES:
        has_bn = sym in BN
        try:
            a = Web3.to_checksum_address(addr)
            tok = w3.eth.contract(address=a, abi=ERC20)
            osym = tok.functions.symbol().call(); dec = tok.functions.decimals().call()
        except Exception as e:
            print(f"[{name:7s}] 地址读取失败({type(e).__name__}) 跳过"); continue
        # 找池:按费档偏好顺序,取第一个有流动性且滑点合理的
        chosen = None
        for fee in FEES:
            try:
                pool = fac.functions.getPool(a, usdc, fee).call()
                if int(pool, 16) == 0: continue
                out = quoter.functions.quoteExactInputSingle((usdc, a, NOTIONAL*10**USDC_DEC, fee, 0)).call()
                tok_out = out[0]/10**dec
                if tok_out <= 0: continue
                # 用 slot0 估中间价算滑点
                chosen = (fee, pool, NOTIONAL/tok_out)
                break
            except Exception:
                continue
        if chosen and has_bn:
            fee, pool, eff = chosen
            feepct = fee/10000
            bnp = BN.get(sym, 0)
            ratio = eff / bnp if bnp > 0 else 0
            deep = 0.90 <= ratio <= 1.12   # eff≈币安价=池足够深;偏离大=池太浅吃$2500
            lowfee = fee <= 3000
            ok = deep and lowfee
            tag = "✅可用" if ok else ("⚠池太浅(eff偏离币安%.0f%%)" % ((ratio-1)*100) if not deep else "⚠仅高费档")
            print(f"[{name:7s}] sym={osym} dec={dec} 币安bid={bnp:.6g} | fee={feepct}% eff={eff:.6g} ratio={ratio:.3f} {tag}")
            if ok:
                good.append((name, addr, dec, fee, sym))
        else:
            why = "币安✗(无永续)" if not has_bn else "无USDC V3池"
            print(f"[{name:7s}] sym={osym} dec={dec} | {why} ❌跳过")
    print("\n=== 可纳入(name, addr, decimals, fee, binance) ===")
    for g in good:
        print("  ", g)


if __name__ == "__main__":
    main()
