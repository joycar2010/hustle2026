"""一次性探测:核实候选标的的链上 symbol/decimals + Uniswap V3 USDC 池可用性 + 试报价。
只把通过的标的纳入默认市场。用法: python probe_markets.py
"""
from web3 import Web3

RPC = "https://mainnet.base.org"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_DEC = 6
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
FEES = [100, 500, 3000, 10000]

# 候选(名称, 地址, 币安USDT永续) —— 地址凭记忆,本脚本就是来核实它们的
CANDIDATES = [
    ("WETH", "0x4200000000000000000000000000000000000006", "ETHUSDT"),
    ("cbBTC", "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "BTCUSDT"),
    ("VIRTUAL", "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b", "VIRTUALUSDT"),
    ("AERO", "0x940181a94A35A4569E4529A3CDfB74e38FD98631", "AEROUSDT"),
    ("DEGEN", "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed", "DEGENUSDT"),
    ("cbETH", "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22", "ETHUSDT"),
]

ERC20 = [
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
]
FACTORY_ABI = [{"inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}], "name": "getPool",
                "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"}]
POOL_ABI = [{"inputs": [], "name": "liquidity", "outputs": [{"type": "uint128"}], "stateMutability": "view", "type": "function"}]
QUOTER_ABI = [{"inputs": [{"components": [
    {"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"},
    {"name": "amountIn", "type": "uint256"}, {"name": "fee", "type": "uint24"},
    {"name": "sqrtPriceLimitX96", "type": "uint160"}], "name": "params", "type": "tuple"}],
    "name": "quoteExactInputSingle",
    "outputs": [{"name": "amountOut", "type": "uint256"}, {"name": "a", "type": "uint160"},
                {"name": "b", "type": "uint32"}, {"name": "c", "type": "uint256"}],
    "stateMutability": "nonpayable", "type": "function"}]

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 12}))
factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY), abi=FACTORY_ABI)
quoter = w3.eth.contract(address=Web3.to_checksum_address(QUOTER), abi=QUOTER_ABI)
usdc = Web3.to_checksum_address(USDC)
NOTIONAL = 2500


def main():
    print(f"connected={w3.is_connected()} block={w3.eth.block_number}\n")
    for name, addr, sym in CANDIDATES:
        try:
            a = Web3.to_checksum_address(addr)
            tok = w3.eth.contract(address=a, abi=ERC20)
            onchain_sym = tok.functions.symbol().call()
            dec = tok.functions.decimals().call()
        except Exception as e:
            print(f"[{name}] 地址无效/读取失败: {type(e).__name__} {e}")
            continue
        best = None
        for fee in FEES:
            try:
                pool = factory.functions.getPool(a, usdc, fee).call()
                if int(pool, 16) == 0:
                    continue
                liq = w3.eth.contract(address=Web3.to_checksum_address(pool), abi=POOL_ABI).functions.liquidity().call()
                # 试报价:$2500 USDC -> token
                out = quoter.functions.quoteExactInputSingle((usdc, a, NOTIONAL * 10 ** USDC_DEC, fee, 0)).call()
                tok_out = out[0] / 10 ** dec
                eff = NOTIONAL / tok_out if tok_out else 0
                if best is None or liq > best[1]:
                    best = (fee, liq, pool, eff, tok_out)
            except Exception:
                continue
        if best:
            fee, liq, pool, eff, tok_out = best
            print(f"[{name}] sym={onchain_sym} dec={dec} | 最佳池 fee={fee} liq={liq} pool={pool}")
            print(f"        $ {NOTIONAL} -> {tok_out:.6f} {onchain_sym}  有效价={eff:.4f} USDC | 币安={sym}  ✅可用")
        else:
            print(f"[{name}] sym={onchain_sym} dec={dec} | 无任何 USDC V3 池 ❌跳过")


if __name__ == "__main__":
    main()
