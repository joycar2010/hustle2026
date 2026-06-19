"""Base 主网已核实常量(官方文档 + 链上 symbol() 双重确认,2026-06)。

地址若要换链/换池,只改这里;P0 仅用 Base。
"""

CHAIN_ID = 8453  # Base mainnet

# 代币(链上 symbol() 已确认)
WETH = "0x4200000000000000000000000000000000000006"  # symbol = WETH, decimals 18
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # symbol = USDC, decimals 6 (Base 原生 USDC)
WETH_DECIMALS = 18
USDC_DECIMALS = 6

# Uniswap V3(developers.uniswap.org 官方 Base 部署)
QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"

# 最小 ABI —— 只放用得到的函数
QUOTER_V2_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "internalType": "struct IQuoterV2.QuoteExactInputSingleParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
            {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",  # 经 eth_call 静态调用做报价,不发交易
        "type": "function",
    }
]

FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint24", "name": "", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Base(OP-Stack)预部署 GasPriceOracle —— 实时 L1 data 费
GAS_ORACLE = "0x420000000000000000000000000000000000000F"
GAS_ORACLE_ABI = [
    {
        "inputs": [{"internalType": "bytes", "name": "_data", "type": "bytes"}],
        "name": "getL1Fee",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]
# 代表性 swap 交易字节(用于 getL1Fee 估算,~336B,含零/非零混合);
# L1 费对结果影响 <~1bps@$2500,精确到字节无意义,代表性长度即可。
SWAP_TX_SAMPLE = bytes(range(256)) + bytes(range(80))

# WETH/USDC 0.05% 池(已核实)—— 作为 ETH/USD 参考价,统一用于 gas 折美元
WETH_USDC_REF_POOL = "0xd0b53D9277642d899DF5C87A3966A349A798F224"

POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

Q96 = 2 ** 96
