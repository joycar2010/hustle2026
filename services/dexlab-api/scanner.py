"""dexlab-scanner(D-lab):D1/D2/D4 扫描器 worker——LAB 从『登记壳』变『真实验』的本体。

- 只读公开数据源(DefiLlama/Pendle 公共 API),无 key、无签名、零下单能力;
- 消费 lab_run(state=RUNNING, kind=MEASURE) 决定扫哪些项目——UI『开始扫描』登记的轮次
  在这里真正被执行;停止扫描(state=DONE)即停;
- 产出:lab_signal 逐样本(payload=逐标的折价/利差 bps)+ lab_run.samples/result_bps 累计
  + lab_cost_model(静态成本假设,判定净值用);
- result_bps = 扣成本后中位数机会(负=无套利空间,如实记录);
- 失败逐项目隔离:一个数据源挂了只影响该项目该轮,err 记进 run.note。

D1 可赎回稳定币/LST 折价:市场价 vs 赎回参考价(LST/ETH 比价、稳定币/1)。
D2 PT 固定到期折价:Pendle impliedApy vs underlyingApy(固定收益贴水)。
D4 同币种借贷利差:DefiLlama yields,同资产跨协议(aave/morpho/compound)存借差。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import time
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dexlab-scanner")

DB = "/home/ec2-user/dexlab/dexlab.db"
INTERVAL = 300   # 5min:公开源限频友好;折价/利差变化以小时计

# 成本模型(静态假设,进 lab_cost_model 供判定;后续可按实测更新)
COST_MODEL = {
    "D1": {"round_trip_bps": 25, "note": "DEX swap 5 + gas 5 + 赎回等待资金成本 10 + 滑点 5"},
    "D2": {"round_trip_bps": 40, "note": "Pendle swap 15 + gas 5 + 持有到期资金成本 20"},
    "D4": {"round_trip_bps": 10, "note": "存借各一次 gas + 利率漂移缓冲"},
}


def _get(url: str, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "dexlab-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── D1:LST/可赎回稳定币折价(DefiLlama prices + 链上 exchange rate,免key) ──
_D1_SET = {
    # llama coin id → (名称, 参考资产 llama id, 类型)
    "coingecko:staked-ether": ("stETH", "coingecko:ethereum", "LST(Lido提款队列1:1)"),
    "coingecko:rocket-pool-eth": ("rETH", "coingecko:ethereum", "LST-带息(赎回价=getExchangeRate)"),
    "coingecko:wrapped-beacon-eth": ("wBETH", "coingecko:ethereum", "LST-带息(赎回价=exchangeRate)"),
    "coingecko:ethena-usde": ("USDe", None, "yield-stable(合成美元,非1:1法币赎回)"),
    "coingecko:first-digital-usd": ("FDUSD", None, "stable(法币储备,赎回需KYC)"),
    "coingecko:paypal-usd": ("PYUSD", None, "stable(法币储备,赎回需KYC)"),
}

# 主网 canonical 合约(人工核对;V6.2 §5 instrument registry 最小版)+ 只读 eth_call selector
_D1_CONTRACTS = {
    "rETH": ("0xae78736Cd615f374D3085123A210448E74Fc6393", "0xe6aa216c", "getExchangeRate()→ETH/rETH"),
    "wBETH": ("0xa2E3356610840701BDf5611a53974510Ae27E2e1", "0x3ba0b9a9", "exchangeRate()→ETH/wBETH"),
}
_RPC_URLS = ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com",
             "https://cloudflare-eth.com"]


# ── 纯 Python keccak256:运行时派生 eth_call 选择器(自检失败=禁用派生调用,fail-loud) ──
def _keccak256(data: bytes) -> bytes:
    RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
          0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
          0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
          0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
          0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
          0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
    ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
           [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
    M = 0xFFFFFFFFFFFFFFFF

    def rol(x, n):
        n %= 64
        return ((x << n) | (x >> (64 - n))) & M if n else x
    st = [[0] * 5 for _ in range(5)]
    rate = 136
    p = bytearray(data)
    p.append(0x01)
    while len(p) % rate:
        p.append(0)
    p[-1] ^= 0x80
    for off in range(0, len(p), rate):
        blk = p[off:off + rate]
        for i in range(rate // 8):
            st[i % 5][i // 5] ^= int.from_bytes(blk[i * 8:i * 8 + 8], 'little')
        for rnd in range(24):
            C = [st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4] for x in range(5)]
            D = [C[(x - 1) % 5] ^ rol(C[(x + 1) % 5], 1) for x in range(5)]
            for x in range(5):
                for y in range(5):
                    st[x][y] ^= D[x]
            B = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    B[y][(2 * x + 3 * y) % 5] = rol(st[x][y], ROT[x][y])
            for x in range(5):
                for y in range(5):
                    st[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y])
            st[0][0] ^= RC[rnd]
    out = b''
    for i in range(rate // 8):
        out += st[i % 5][i // 5].to_bytes(8, 'little')
        if len(out) >= 32:
            break
    return out[:32]


def _sel(sig: str) -> str:
    return "0x" + _keccak256(sig.encode()).hex()[:8]


# 自检:空串已知向量 + 两个生产已验证选择器交叉核对;失败=派生调用全禁用
try:
    _KECCAK_OK = (_keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
                  and _sel("getExchangeRate()") == "0xe6aa216c" and _sel("exchangeRate()") == "0x3ba0b9a9")
except Exception:  # noqa: BLE001
    _KECCAK_OK = False
if not _KECCAK_OK:
    log.error("keccak self-test FAILED — derived-selector reads disabled (REDEEM_STATUS unavailable)")


def _rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    last = None
    for u in _RPC_URLS:
        try:
            req = urllib.request.Request(u, data=body, headers={
                "Content-Type": "application/json", "User-Agent": "dexlab-scanner/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                out = json.loads(r.read().decode())
            if "result" in out:
                return out["result"], u
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"all RPC failed: {last!r}")


def _d1_exchange_rates():
    """链上赎回参考价(公共 RPC 只读 eth_call)。任一标的失败=缺该标的,绝不猜。"""
    blk_hex, rpc_used = _rpc("eth_blockNumber", [])
    blk = int(blk_hex, 16)
    rates = {}
    for name, (addr, sel, _note) in _D1_CONTRACTS.items():
        try:
            res, _ = _rpc("eth_call", [{"to": addr, "data": sel}, "latest"])
            rates[name] = int(res, 16) / 1e18
        except Exception as e:  # noqa: BLE001
            log.warning("D1 rate %s failed: %r", name, e)
    return rates, blk, rpc_used


# ── D1 REDEEM_STATUS:赎回可行性链上直读(证据类型 REDEEM_STATUS 的数据源) ──
_LIDO_WQ = "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1"   # Lido WithdrawalQueue(主网 canonical)


def _d1_redeem_status() -> dict:
    if not _KECCAK_OK:
        raise RuntimeError("keccak self-test failed, derived selectors disabled")

    def call_u(addr, sig):
        res, _ = _rpc("eth_call", [{"to": addr, "data": _sel(sig)}, "latest"])
        return int(res, 16)
    st = {"lido_wq_paused": bool(call_u(_LIDO_WQ, "isPaused()")),
          "lido_bunker_mode": bool(call_u(_LIDO_WQ, "isBunkerModeActive()"))}
    unf = call_u(_LIDO_WQ, "unfinalizedStETH()") / 1e18
    col = call_u(_D1_CONTRACTS["rETH"][0], "getTotalCollateral()") / 1e18
    if unf > 1e8 or col > 1e8:
        raise RuntimeError(f"implausible values unf={unf} col={col} (selector/ABI 疑似不对,拒绝采信)")
    st["lido_unfinalized_steth"] = round(unf, 1)
    st["reth_instant_burn_capacity_eth"] = round(col, 1)
    st["wbeth_note"] = "wBETH 赎回走 Binance 渠道,链上无公开赎回队列——该标的赎回状态=受限(按 CEX 路径评估)"
    return st


# ── D1 TARGET_QUOTE:目标金额真实报价(Kyber 聚合器,免key;§6.3 size ladder 最小版) ──
_D1_TOKENS = {"stETH": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
              "rETH": "0xae78736Cd615f374D3085123A210448E74Fc6393",
              "wBETH": "0xa2E3356610840701BDf5611a53974510Ae27E2e1"}
_WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
_QUOTE_SIZES_ETH = (10, 100)


def _kyber_out_wei(token_in: str, token_out: str, amount_in_wei: int) -> int:
    d = _get("https://aggregator-api.kyberswap.com/ethereum/api/v1/routes"
             f"?tokenIn={token_in}&tokenOut={token_out}&amountIn={amount_in_wei}")
    out = int(((d.get("data") or {}).get("routeSummary") or {}).get("amountOut") or 0)
    if out <= 0:
        raise RuntimeError("no route / empty amountOut")
    return out


def _d1_quotes(redemptions: dict) -> dict:
    """买入侧真报价:WETH→LST 按 size ladder;可执行折价=1-(实付ETH/枚 ÷ 赎回价)。
    正=能以低于赎回价值的成本买入(毛边际,未扣gas/排队资金成本)。"""
    quotes = {}
    for name, addr in _D1_TOKENS.items():
        red = redemptions.get(name)
        if not red:
            continue
        rows = []
        for sz in _QUOTE_SIZES_ETH:
            try:
                lst_out = _kyber_out_wei(_WETH, addr, sz * 10 ** 18) / 1e18
                eth_per_lst = sz / lst_out
                rows.append({"size_eth": sz, "lst_out": round(lst_out, 6),
                             "eth_per_lst": round(eth_per_lst, 6),
                             "exec_discount_bps": round((1 - eth_per_lst / red) * 10000, 1)})
            except Exception as e:  # noqa: BLE001
                rows.append({"size_eth": sz, "error": repr(e)[:80]})
            time.sleep(0.4)
        quotes[name] = rows
    return quotes


def scan_d1():
    """返回 {signals, evidence, extra}:折价口径=市场比价 vs 链上赎回价(V6.2 §8——
    带息 LST 比价>1 是正常计息,naive 1-ratio 会把计息记成溢价)。"""
    ids = list(_D1_SET) + ["coingecko:ethereum"]
    data = _get("https://coins.llama.fi/prices/current/" + ",".join(ids))
    px = {k: v.get("price") for k, v in (data.get("coins") or {}).items()}
    eth = px.get("coingecko:ethereum")
    rates, blk, rpc_used = {}, None, ""
    try:
        rates, blk, rpc_used = _d1_exchange_rates()
    except Exception as e:  # noqa: BLE001
        log.warning("D1 onchain rates unavailable: %r", e)
    out = []
    for cid, (name, ref, kind) in _D1_SET.items():
        p = px.get(cid)
        if p is None:
            continue
        if ref:   # LST:市场比价 vs 赎回参考价
            if not eth:
                continue
            ratio = p / eth
            if name == "stETH":
                redemption = 1.0   # Lido 提款队列 1:1(排队时长另计,进 REDEEM_STATUS 证据)
            else:
                redemption = rates.get(name)
            row = {"asset": name, "kind": kind, "price": p, "market_ratio": round(ratio, 6)}
            if redemption:
                row["redemption_rate"] = round(redemption, 6)
                row["rate_source"] = "onchain" if name in rates else "protocol_1to1"
                row["discount_bps"] = round((1 - ratio / redemption) * 10000, 1)
            else:
                # 无链上赎回价→只记比价不给折价(缺证据就缺,不用错口径凑数)
                row["rate_source"] = "MISSING_ONCHAIN_RATE"
            out.append(row)
        else:     # 稳定币:对 1 美元偏离(仅 peg 观察;赎回资格/额度是另一回事)
            out.append({"asset": name, "kind": kind, "price": p,
                        "discount_bps": round((1 - p) * 10000, 1)})
    # ── 赎回状态 + 目标金额真报价(证据闸后两块;逐块失败隔离,缺=闸如实缺) ──
    redeem, quotes = None, {}
    try:
        redeem = _d1_redeem_status()
    except Exception as e:  # noqa: BLE001
        log.warning("D1 redeem status unavailable: %r", e)
    try:
        quotes = _d1_quotes({"stETH": 1.0, **rates})
    except Exception as e:  # noqa: BLE001
        log.warning("D1 quotes unavailable: %r", e)
    for row in out:
        q = quotes.get(row["asset"])
        if q:
            row["quotes"] = q
    evidence = []
    if rates:
        evidence.append({
            "etype": "EXCHANGE_RATE", "ttl": 24 * 3600, "source": rpc_used,
            "title": f"链上兑换率快照 block {blk}",
            "body": json.dumps({"block_number": blk, "rates_eth": {k: round(v, 6) for k, v in rates.items()},
                                "stETH": "1.0(Lido提款队列1:1)", "rpc": rpc_used}, ensure_ascii=False)})
        evidence.append({
            "etype": "CONTRACT_IDENTITY", "ttl": None, "source": "static-registry(人工核对 2026-07-17)",
            "title": "D1 标的主网 canonical 合约登记",
            "body": json.dumps({k: {"contract": v[0], "method": v[2]} for k, v in _D1_CONTRACTS.items()},
                               ensure_ascii=False)})
    if redeem:
        evidence.append({
            "etype": "REDEEM_STATUS", "ttl": 24 * 3600, "source": rpc_used or "eth_call",
            "title": f"赎回可行性链上快照 block {blk or '?'}",
            "body": json.dumps(redeem, ensure_ascii=False)})
    ok_quotes = {k: [r for r in v if "error" not in r] for k, v in quotes.items()}
    ok_quotes = {k: v for k, v in ok_quotes.items() if v}
    if ok_quotes:
        evidence.append({
            "etype": "TARGET_QUOTE", "ttl": 4 * 3600, "dedupe": 3600,
            "source": "kyberswap-aggregator(真路由报价)",
            "title": f"目标金额买入报价({'/'.join(str(s) for s in _QUOTE_SIZES_ETH)} ETH)",
            "body": json.dumps(ok_quotes, ensure_ascii=False)})
    extra = {}
    if redeem:
        extra["redeem_status"] = redeem
    return {"signals": out, "evidence": evidence, "extra": extra}


# ── D2:Pendle PT 固定收益贴水(公共 API + 链上 expiry() 核验) ─────────────
def scan_d2():
    """返回 {signals, evidence}。口径(§9.2):
    - spread_bps=隐含-底层收益率差(年化,非本笔利润);
    - maturity_gross_discount_bps=到期毛折价(API ptDiscount,与 (1+imp)^-T 派生值交叉核对,
      偏差>50bps 标 DISCOUNT_SOURCE_DIVERGENT);
    - maturity_window_return_pct=持有到期窗口毛收益(**计价=accountingAsset 资产本位,未扣
      swap/gas/兑付/资金成本**,净收益仍待计算)。"""
    data = _get("https://api-v2.pendle.finance/core/v1/1/markets?limit=20&is_active=true")
    out = []
    now_utc = datetime.now(timezone.utc)
    for m in (data.get("results") or [])[:20]:
        try:
            imp = float(m.get("impliedApy") or 0) * 100
            und = float((m.get("underlyingApy") or 0)) * 100
            name = ((m.get("pt") or {}).get("symbol")) or m.get("symbol") or "?"
            expiry = m.get("expiry")
            days = None
            expiry_ts = None
            if expiry:
                try:
                    dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                    expiry_ts = int(dt.timestamp())
                    days = max(0.0, round((dt - now_utc).total_seconds() / 86400, 1))
                except Exception:  # noqa: BLE001
                    pass
            acct = m.get("accountingAsset") or {}
            row = {"asset": name, "implied_apy_pct": round(imp, 3),
                   "underlying_apy_pct": round(und, 3),
                   "spread_bps": round((imp - und) * 100, 1),
                   "expiry": expiry, "days_to_maturity": days,
                   "accounting_asset": acct.get("symbol") or "",
                   "pt_address": ((m.get("pt") or {}).get("address")) or "",
                   "_expiry_ts": expiry_ts, "_market": m.get("address") or "",
                   "_acct_addr": acct.get("address") or "",
                   "_acct_dec": int(acct.get("decimals") or 18),
                   "_pt_dec": int(((m.get("pt") or {}).get("decimals")) or 18)}
            ptd = m.get("ptDiscount")
            if days and days > 0:
                t_years = days / 365.0
                derived_bps = (1 - (1 + imp / 100) ** (-t_years)) * 10000
                row["maturity_window_return_pct"] = round(((1 + imp / 100) ** t_years - 1) * 100, 2)
                if ptd is not None:
                    api_bps = float(ptd) * 10000
                    row["maturity_gross_discount_bps"] = round(api_bps, 1)
                    if abs(api_bps - derived_bps) > 50:
                        row["discount_source_divergent"] = round(api_bps - derived_bps, 1)
                else:
                    row["maturity_gross_discount_bps"] = round(derived_bps, 1)
            out.append(row)
        except Exception:  # noqa: BLE001
            continue
    # ── 链上核验:利差前3的市场 PT.expiry() 对照 API(证据=真链上读) ──
    evidence = []
    verified = []
    top3 = sorted([r for r in out if r.get("pt_address") and r.get("_expiry_ts")],
                  key=lambda r: -r["spread_bps"])[:3]
    if _KECCAK_OK:
        for row in top3:
            try:
                res, rpc_used = _rpc("eth_call", [{"to": row["pt_address"], "data": _sel("expiry()")}, "latest"])
                chain_ts = int(res, 16)
                ok = abs(chain_ts - row["_expiry_ts"]) < 86400
                row["expiry_onchain_verified"] = ok
                if ok:
                    verified.append({"pt": row["asset"], "address": row["pt_address"],
                                     "chain_expiry_ts": chain_ts, "api_expiry": row["expiry"], "rpc": rpc_used})
                else:
                    log.warning("D2 expiry mismatch %s chain=%s api=%s", row["asset"], chain_ts, row["_expiry_ts"])
            except Exception as e:  # noqa: BLE001
                log.warning("D2 expiry() check failed %s: %r", row["asset"], e)
            time.sleep(0.3)
    # ── TARGET_QUOTE:前3市场 Pendle v2 SDK 真报价(买入侧,accounting asset→PT) ──
    quote_rows = []
    for row in top3:
        if not (row.get("_market") and row.get("_acct_addr") and row.get("pt_address")):
            continue
        qs = []
        for size in (1_000, 10_000):   # accounting asset 单位(稳定计价≈USD;非稳定资产本位)
            try:
                amt_in = size * 10 ** row["_acct_dec"]
                d = _get("https://api-v2.pendle.finance/core/v2/sdk/1/markets/"
                         f"{row['_market']}/swap?receiver=0x000000000000000000000000000000000000dEaD"
                         f"&slippage=0.01&enableAggregator=true&tokenIn={row['_acct_addr']}"
                         f"&tokenOut={row['pt_address']}&amountIn={amt_in}")
                dd = d.get("data") or {}
                pt_out = int(dd.get("amountOut") or 0) / 10 ** row["_pt_dec"]
                if pt_out <= 0:
                    raise RuntimeError("empty amountOut")
                # 1 PT 到期兑付 1 accounting asset → 可执行到期折价=1-(实付/枚)
                q = {"size": size, "pt_out": round(pt_out, 4),
                     "asset_per_pt": round(size / pt_out, 6),
                     "exec_maturity_discount_bps": round((1 - size / pt_out) * 10000, 1),
                     "price_impact_pct": round(float(dd.get("priceImpact") or 0) * 100, 4)}
                # 交叉核对:可执行折价 vs API ptDiscount 口径;分歧>200bps=兑付假设可能
                # 不适用该市场(1PT≠1acct)或计价资产/路由异常——标记待人工复核,绝不硬显示
                api_disc = row.get("maturity_gross_discount_bps")
                if api_disc is not None and abs(q["exec_maturity_discount_bps"] - api_disc) > 200:
                    q["quote_model_divergent_bps"] = round(q["exec_maturity_discount_bps"] - api_disc, 1)
                qs.append(q)
            except Exception as e:  # noqa: BLE001
                qs.append({"size": size, "error": repr(e)[:80]})
            time.sleep(0.4)
        if qs:
            row["pt_quotes"] = qs
            if any("error" not in q for q in qs):
                quote_rows.append({"pt": row["asset"], "market": row["_market"],
                                   "accounting_asset": row["accounting_asset"], "quotes": qs})
    for r in out:
        for k in ("_expiry_ts", "_market", "_acct_addr", "_acct_dec", "_pt_dec"):
            r.pop(k, None)
    if verified:
        evidence.append({"etype": "MATURITY_ONCHAIN", "ttl": 7 * 24 * 3600, "source": "eth_call expiry()",
                         "title": f"PT 到期链上核验({len(verified)} 市场,chain==API)",
                         "body": json.dumps(verified, ensure_ascii=False)})
        evidence.append({"etype": "CONTRACT_IDENTITY", "ttl": None,
                         "source": "pendle-api + onchain expiry() 交叉核验",
                         "title": "D2 PT 合约身份登记(链上到期核验通过的市场)",
                         "body": json.dumps([{"pt": v["pt"], "address": v["address"]} for v in verified],
                                            ensure_ascii=False)})
        # 兑付模型:Pendle 协议级事实(到期 1 PT = 1 accounting asset,经 Router redeemPy)
        # + 逐市场计价资产映射;非稳定计价=资产本位(settlement_class 按 accounting asset 归类)
        evidence.append({"etype": "REDEMPTION_MODEL", "ttl": 7 * 24 * 3600, "dedupe": 24 * 3600,
                         "source": "pendle 协议通用兑付模型 + API accountingAsset 映射",
                         "title": "D2 兑付模型登记(链上核验市场)",
                         "body": json.dumps([{
                             "pt": v["pt"],
                             "model": "到期 1 PT = 1 accounting asset;赎回路径=expiry 后经 Pendle Router redeemPy",
                             "accounting_asset": next((r["accounting_asset"] for r in top3
                                                       if r["asset"] == v["pt"]), ""),
                             "settlement_class": ("HARD_STABLE" if any(
                                 s in next((r["accounting_asset"] for r in top3 if r["asset"] == v["pt"]), "").upper()
                                 for s in ("USD", "DAI", "FRAX")) else "ASSET_UNIT_HARD_USD_FLOATING")}
                             for v in verified], ensure_ascii=False)})
    if quote_rows:
        evidence.append({"etype": "TARGET_QUOTE", "ttl": 4 * 3600, "dedupe": 3600,
                         "source": "pendle-v2-sdk swap 真报价",
                         "title": "PT 目标金额买入报价(1k/10k accounting asset)",
                         "body": json.dumps(quote_rows, ensure_ascii=False)})
    return {"signals": out, "evidence": evidence}


# ── D4:同币种跨协议借贷利差(DefiLlama yields,免key) ─────────────────────
def scan_d4() -> list[dict]:
    data = _get("https://yields.llama.fi/pools")
    rows = data.get("data") or []
    keep = [r for r in rows
            if r.get("chain") == "Ethereum"
            and r.get("project") in ("aave-v3", "morpho-blue", "compound-v3", "spark")
            and r.get("symbol") in ("USDC", "USDT", "DAI", "WETH")
            and (r.get("tvlUsd") or 0) > 5_000_000]
    by_sym: dict[str, list] = {}
    for r in keep:
        by_sym.setdefault(r["symbol"], []).append(r)
    out = []
    for sym, ps in by_sym.items():
        if len(ps) < 2:
            continue
        best = max(ps, key=lambda x: x.get("apyBase") or 0)
        worst = min(ps, key=lambda x: x.get("apyBase") or 0)
        out.append({"asset": sym,
                    "best": f"{best['project']} {round(best.get('apyBase') or 0, 2)}%",
                    "worst": f"{worst['project']} {round(worst.get('apyBase') or 0, 2)}%",
                    "spread_bps": round(((best.get("apyBase") or 0) - (worst.get("apyBase") or 0)) * 100, 1),
                    "pools": len(ps)})
    return out


_SCANNERS = {"D1": scan_d1, "D2": scan_d2, "D4": scan_d4}


def _register_evidence(c, pid: str, ev: dict, now: int):
    """typed 证据自动登记(真实链上/来源数据才登记;去重=同类型6h内有效证据不重复)。"""
    etype = ev["etype"]
    row = c.execute("SELECT created_at, expires_at FROM lab_evidence WHERE project_id=? "
                    "AND evidence_type=? ORDER BY id DESC LIMIT 1", (pid, etype)).fetchone()
    if row:
        created, expires = row[0] or 0, row[1]
        if ev.get("ttl") is None:
            return   # 永久型(合约身份)只登记一次
        if now - created < ev.get("dedupe", 6 * 3600) and (expires is None or expires > now):
            return
    c.execute("INSERT INTO lab_evidence(project_id,run_id,kind,title,body,created_at,"
              "evidence_type,source,observed_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (pid, None, "typed", ev["title"][:120], ev["body"][:2000], now,
               etype, ev.get("source", "")[:120], now,
               (now + ev["ttl"]) if ev.get("ttl") else None))
    log.info("%s evidence registered: %s", pid, etype)


def run_replay(c: sqlite3.Connection, run_id: int, pid: str, params: dict, now: int):
    """回放执行器(V6.2 L4 v1)。口径=**重放已采样的 lab_signal 历史,非链上区块重演**;
    产出=超成本占比/持续性/瞬时信号率/净p50 → 人工评审素材,不自动晋级。"""
    days = float(params.get("days") or 30)
    since = now - int(days * 86400)
    rows = list(c.execute("SELECT ts, payload FROM lab_signal WHERE project_id=? AND ts>=? ORDER BY ts",
                          (pid, since)))
    cost = COST_MODEL.get(pid, {}).get("round_trip_bps", 0)
    series = []
    for ts, pl in rows:
        try:
            p = json.loads(pl)
            b = p.get("best_bps")
            if b is None:   # 旧 payload(净口径时代)回落:net+cost 还原 raw
                b = (p.get("net_best_bps") or 0) + (p.get("cost_bps") or 0)
            series.append((ts, float(b)))
        except Exception:  # noqa: BLE001
            continue
    n = len(series)
    if n < 12:
        c.execute("UPDATE lab_run SET state='FAILED', ended_at=?, note=? WHERE run_id=?",
                  (now, f"历史样本不足({n}轮<12)——先积累测量数据再回放", run_id))
        log.warning("%s replay #%s failed: only %d samples", pid, run_id, n)
        return
    bests = sorted(b for _, b in series)
    p50 = bests[n // 2]
    p90 = bests[min(n - 1, int(n * 0.9))]
    above = [b > cost for _, b in series]
    pct_above = round(100 * sum(above) / n, 1)
    cur = longest = 0
    for a in above:
        cur = cur + 1 if a else 0
        longest = max(longest, cur)
    trans, tot = 0, 0
    for i in range(n - 1):
        if above[i]:
            tot += 1
            if not above[i + 1]:
                trans += 1
    transient = round(100 * trans / tot, 1) if tot else None
    stats = {"window_days": days, "rounds": n, "cost_bps": cost,
             "best_p50_bps": round(p50, 1), "best_p90_bps": round(p90, 1),
             "pct_rounds_above_cost": pct_above, "longest_streak_rounds": longest,
             "transient_signal_rate_pct": transient, "net_p50_bps": round(p50 - cost, 1),
             "span_ts": [series[0][0], series[-1][0]],
             "note": "口径=重放已采样lab_signal历史(5min粒度),非链上区块重演;假阳性以瞬时率近似"}
    note = (f"回放{days:g}天{n}轮:超成本占比{pct_above}%·最长连续{longest}轮·"
            f"瞬时信号率{transient if transient is not None else '—'}%·净p50={round(p50 - cost, 1)}bps")
    c.execute("UPDATE lab_run SET state='DONE', ended_at=?, samples=?, result_bps=?, params=?, note=? "
              "WHERE run_id=?", (now, n, round(p50 - cost, 1),
                                 json.dumps({**params, "stats": stats}, ensure_ascii=False), note, run_id))
    c.execute("INSERT INTO research_outbox(project_id,title,summary,severity,created_at,"
              "artifact_type,schema_version) VALUES(?,?,?,?,?,'LAB_RUN_COMPLETED',2)",
              (pid, f"{pid} 回放完成(#{run_id})",
               note + "\n" + stats["note"] + f"\n窗口:{days:g}天 成本假设:{cost}bps p90={round(p90, 1)}bps",
               "info", now))
    log.info("%s replay #%s done: %s", pid, run_id, note)


def loop_once(c: sqlite3.Connection):
    now = int(time.time())
    # ── REPLAY 轮次:一次性执行(历史重放),完成即 DONE ──
    for run_id, pid, params_s in list(c.execute(
            "SELECT run_id, project_id, params FROM lab_run WHERE state='RUNNING' AND kind='REPLAY'")):
        try:
            run_replay(c, run_id, pid, json.loads(params_s or "{}"), now)
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE lab_run SET state='FAILED', ended_at=?, note=? WHERE run_id=?",
                      (now, f"REPLAY ERR:{repr(e)[:120]}", run_id))
            log.warning("%s replay #%s crashed: %r", pid, run_id, e)
        c.commit()   # 逐轮即时提交,绝不带着写锁跨网络请求(database is locked 课)
    runs = list(c.execute(
        "SELECT run_id, project_id FROM lab_run WHERE state='RUNNING' AND kind='MEASURE'"))
    for run_id, pid in runs:
        fn = _SCANNERS.get(pid)
        if fn is None:
            continue   # R1 由 xv 采样器负责,其余项目无扫描器=如实不动
        try:
            res = fn()
            sigs = res["signals"] if isinstance(res, dict) else res
            if not sigs:
                raise RuntimeError("empty result")
            for ev in (res.get("evidence") or []) if isinstance(res, dict) else []:
                _register_evidence(c, pid, ev, now)
            cost = COST_MODEL.get(pid, {}).get("round_trip_bps", 0)
            # 机会口径:D1 取『折价』正向(vs 赎回价);D2/D4 取 spread;无口径的行(缺链上rate)不进统计
            vals = [v for v in (s.get("discount_bps", s.get("spread_bps")) for s in sigs) if v is not None]
            if not vals:
                raise RuntimeError("no measurable rows (missing onchain rates?)")
            med = round(statistics.median(vals), 1)
            best = round(max(vals), 1)
            net_best = round(best - cost, 1)
            # V6.2 §6.1:raw_signal 与 economic_net_result 拆开——粗成本常数只作参考,
            # 不得再把 best-cost 标成『净最优』;可执行净收益=待计算(需目标金额真实报价)
            kind = {"D1": "RAW_DISCOUNT", "D2": "IMPLIED_YIELD_SPREAD",
                    "D4": "VARIABLE_RATE_MONITOR"}.get(pid, "RAW_SIGNAL")
            payload = {"signal_kind": kind, "signals": sigs, "median_bps": med,
                       "best_bps": best, "cost_bps": cost, "net_best_bps": net_best,
                       "net_state": "PENDING_CALCULATION"}
            if isinstance(res, dict) and res.get("extra"):
                payload.update(res["extra"])
            c.execute("INSERT INTO lab_signal(project_id, ts, payload) VALUES(?,?,?)",
                      (pid, now, json.dumps(payload, ensure_ascii=False)))
            c.execute("UPDATE lab_run SET samples=samples+?, result_bps=?, note=? WHERE run_id=?",
                      (len(sigs), best,
                       f"初步信号最优={best}bps 中位={med}(参考成本{cost}bps;可执行净收益待计算)", run_id))
            c.execute("INSERT INTO lab_cost_model(project_id, model, updated_at) VALUES(?,?,?) "
                      "ON CONFLICT(project_id) DO UPDATE SET model=excluded.model, updated_at=excluded.updated_at",
                      (pid, json.dumps(COST_MODEL.get(pid, {}), ensure_ascii=False), now))
            c.execute("UPDATE lab_project SET stage='MEASURE', updated_at=? WHERE project_id=?", (now, pid))
            log.info("%s: %d signals, net_best=%.1fbps", pid, len(sigs), net_best)
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE lab_run SET note=? WHERE run_id=?", (f"ERR:{repr(e)[:120]}", run_id))
            log.warning("%s scan failed: %r", pid, e)
        # 逐项目即时提交:下一项目的网络请求(报价含 sleep)绝不发生在持写锁的事务里
        c.commit()
    c.commit()


def main():
    log.info("dexlab-scanner up interval=%ss scanners=%s", INTERVAL, list(_SCANNERS))
    while True:
        try:
            c = sqlite3.connect(DB, timeout=30)
            c.execute("PRAGMA busy_timeout=15000")
            loop_once(c)
            c.close()
        except Exception:  # noqa: BLE001
            log.exception("scan round crashed (continuing)")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
