# Asset 360 单币全景核心模块（MIX-V6.2-ASSET360-PATCH-01 A1-A3）
# 为 C2.P 人工研判、C3 借币点差、AiCoin 工作台提供统一跨平台事实快照。
# 不新增左侧菜单，抽屉/全屏入口从今日工作/策略表/AiCoin 搜索复用。
import asyncio
import time
import json
import hashlib
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any
from app import datasources as ds

log = logging.getLogger(__name__)

# ══ §3 Canonical Asset 身份映射 ═══════════════════════════════════════════
# 不按 ticker 聚合（BTC/XBT、PEPE/1000PEPE 坑多），用版本化映射表。
_KNOWN_ALIASES = {
    "BTC": ["XBT", "BTCPERP"],
    "PEPE": ["1000PEPE"],
    "SHIB": ["1000SHIB"],
    "FLOKI": ["1000FLOKI"],
}
_MULTIPLIER_CONTRACTS = {
    "1000PEPE": {"base": "PEPE", "multiplier": 1000},
    "1000SHIB": {"base": "SHIB", "multiplier": 1000},
    "1000FLOKI": {"base": "FLOKI", "multiplier": 1000},
}
_VENUES = ["binance", "okx", "bybit", "gate", "bitget", "hyperliquid"]

# ══ §4 MetricValueEnvelope 八态 ═══════════════════════════════════════════
def _mv(value=None, state="PRESENT", source=None, source_time=None, unit=None, missing_reason=None):
    """MetricValueEnvelope: value/state/source/source_time/stale_after/confidence/missing_reason。
    state: PRESENT|ZERO|NOT_APPLICABLE|NOT_CONNECTED|UNKNOWN|STALE|MAINTENANCE|CONFLICT|ERROR"""
    return {
        "value": value, "state": state, "unit": unit,
        "source": source, "source_time": source_time,
        "missing_reason": missing_reason,
    }

def _norm_sym(s: str) -> str:
    """归一化 symbol：去横杠、下划线、SWAP 后缀，全大写。"""
    return str(s or "").upper().replace("-", "").replace("_", "").replace("SWAP", "")

def _match_alias(sym: str) -> str:
    """按已知别名映射到 canonical symbol；未知返回原值。"""
    ns = _norm_sym(sym)
    for canon, aliases in _KNOWN_ALIASES.items():
        if ns == canon or ns in [_norm_sym(a) for a in aliases]:
            return canon
    # 乘数合约归基础
    for k, v in _MULTIPLIER_CONTRACTS.items():
        if ns == _norm_sym(k):
            return v["base"]
    return ns[:-4] if ns.endswith("USDT") else ns

def _get_multiplier(sym: str) -> Decimal:
    """获取合约乘数（1000PEPE=1000）；普通币=1。"""
    ns = _norm_sym(sym)
    for k, v in _MULTIPLIER_CONTRACTS.items():
        if ns == _norm_sym(k):
            return Decimal(v["multiplier"])
    return Decimal(1)

# ══ §5 六所行情聚合（价格/OI/资金费归一 USD）═════════════════════════════
async def _venue_markets(venue: str, canonical: str) -> dict:
    """单所单币市场快照：现货/永续价格、24h量、OI、资金费（归一日化%）。
    数据源优先级：①dcm:account:{venue}.pos_detail（mark/upnl/dist_liq/adl，REV4批A已通）
               ②dcm:feed:funding:{venue} Redis hash（daily_pct/interval_h，REV4批A已通）
               ③公开ticker（A1补：无持仓时从公开行情取mark，避免NOT_CONNECTED）。"""
    now_ts = time.time()
    # 从 account-snapshot 取持仓级事实（mark/liq/upnl/adl）
    acct = await ds.get_json(f"dcm:account:{venue}") or {}
    pd = acct.get("pos_detail") or {}
    pos = None
    for k, v in pd.items():
        if _match_alias(k) == canonical:
            pos = v
            break
    # 从 funding feed 取资金费
    r = ds.rds()
    funding_daily, funding_interval = None, None
    mark_price = pos.get("mark") if pos else None  # 优先用持仓 mark
    if r:
        try:
            # 资金费
            for suffix in ["", "USDT", "_USDT", "-USDT", "PERP"]:
                fv = await r.hget(f"dcm:feed:funding:{venue}", canonical + suffix)
                if fv:
                    fe = json.loads(fv)
                    funding_daily = fe.get("daily_pct")
                    funding_interval = fe.get("interval_h")
                    # A1补：无持仓时从funding feed取mark（币安/OKX/Bybit feed都带mark字段）
                    if mark_price is None and fe.get("mark"):
                        mark_price = fe.get("mark")
                    break
        except Exception:  # noqa: BLE001
            pass
    # TODO A1后续：补24h量/OI公开采集（币安/ticker/24hr、OKX/market/tickers）
    return {
        "venue": venue,
        "canonical": canonical,
        "spot_price": _mv(None, "NOT_CONNECTED", venue, None, "USD"),
        "perp_mark": _mv(mark_price, "PRESENT" if mark_price else "NOT_CONNECTED", venue,
                        acct.get("ts") or now_ts, "USD"),
        "perp_upnl": _mv(pos.get("upnl") if pos else None,
                        "PRESENT" if pos else "NOT_APPLICABLE", venue,
                        acct.get("ts"), "USD"),
        "dist_liq_pct": _mv(pos.get("dist_liq_pct") if pos else None,
                           "PRESENT" if pos else "NOT_APPLICABLE", venue,
                           acct.get("ts"), "%"),
        "adl": _mv(pos.get("adl") if pos else None,
                  "PRESENT" if pos else "NOT_APPLICABLE", venue,
                  acct.get("ts")),
        "funding_daily_pct": _mv(funding_daily, "PRESENT" if funding_daily else "NOT_CONNECTED",
                                 f"funding:{venue}", now_ts, "%/day"),
        "funding_interval_h": _mv(funding_interval, "PRESENT" if funding_interval else "NOT_CONNECTED",
                                  f"funding:{venue}", now_ts, "hours"),
        "turnover_24h_usd": _mv(None, "NOT_CONNECTED", venue, None, "USD"),
        "oi_usd": _mv(None, "NOT_CONNECTED", venue, None, "USD"),
    }

# ══ §A2 充提网络状态（简化版：币级摘要，详细网络留 A5 优化） ═════════════
async def _venue_networks(venue: str, canonical: str) -> list[dict]:
    """单所单币充提状态摘要。
    A2 简化版：由于币安 /sapi/v1/capital/config/getall 需签名非公开，OKX/Bybit 类似，
    且 cred-agent 架构改造耗时，A2 阶段只返回币级摘要占位，详细逐网络状态留 A5 优化
    （届时统一从 cred-agent 定时采集并缓存到 Redis）。"""
    # A2 简化：返回币级摘要占位
    return [
        {
            "venue": venue,
            "canonical": canonical,
            "network": "summary",  # 标记为摘要行
            "deposit_status": "NOT_CONNECTED",  # A5 补：从 cred-agent 缓存读取
            "withdrawal_status": "NOT_CONNECTED",
            "note": "详细逐网络状态需签名 API，A5 优化时统一采集",
        }
    ]

def _map_network_chain(network_name: str) -> str:
    """网络名映射到 chain_id（A2 简化版，A3 完善）。"""
    n = network_name.upper()
    if "ETH" in n or "ERC20" in n:
        return "ethereum"
    if "BSC" in n or "BEP20" in n:
        return "binance-smart-chain"
    if "ARB" in n:
        return "arbitrum"
    if "OP" in n and "OPTIMISM" in n:
        return "optimism"
    if "POLYGON" in n or "MATIC" in n:
        return "polygon"
    if "AVAX" in n:
        return "avalanche"
    if "SOL" in n:
        return "solana"
    return network_name.lower()

# ══ §A3 韩国市场+市值 ═════════════════════════════════════════════════════
async def _korea_markets(canonical: str) -> list[dict]:
    """韩国 Upbit/Bithumb KRW 盘口 + 区域溢价五前提闸。
    数据源：Upbit /v1/ticker, Bithumb /public/ticker/{pair} 公开端点 + exchangerate-api USDKRW。"""
    try:
        import httpx
        korea_rows = []
        # 获取 USDKRW 汇率
        async with httpx.AsyncClient(timeout=10) as cli:
            fx_r = await cli.get("https://api.exchangerate-api.com/v4/latest/USD")
            fx_r.raise_for_status()
            fx_data = fx_r.json()
            usdkrw = fx_data.get("rates", {}).get("KRW")
            if not usdkrw:
                return []
            # Upbit
            try:
                upbit_r = await cli.get(f"https://api.upbit.com/v1/ticker?markets=KRW-{canonical}")
                upbit_r.raise_for_status()
                upbit_data = upbit_r.json()
                if upbit_data and len(upbit_data) > 0:
                    tick = upbit_data[0]
                    krw_price = tick.get("trade_price")
                    if krw_price:
                        korea_rows.append({
                            "venue": "upbit",
                            "canonical": canonical,
                            "listed": True,
                            "market_pair": f"KRW-{canonical}",
                            "krw_bid": krw_price,  # Upbit ticker 只有 trade_price
                            "krw_ask": krw_price,
                            "krw_mid": krw_price,
                            "normalized_price_usd": krw_price / usdkrw,
                            "turnover_24h_krw": tick.get("acc_trade_price_24h"),
                            "fx_rate": usdkrw,
                            "fx_source": "exchangerate-api",
                            "source_time": time.time(),
                        })
            except Exception:  # noqa: BLE001
                pass
            # Bithumb
            try:
                bithumb_r = await cli.get(f"https://api.bithumb.com/public/ticker/{canonical}_KRW")
                bithumb_r.raise_for_status()
                bithumb_data = bithumb_r.json()
                if bithumb_data.get("status") == "0000" and bithumb_data.get("data"):
                    tick = bithumb_data["data"]
                    buy = float(tick["buy_price"]) if tick.get("buy_price") else None
                    sell = float(tick["sell_price"]) if tick.get("sell_price") else None
                    mid = (buy + sell) / 2 if buy and sell else (buy or sell)
                    if mid:
                        korea_rows.append({
                            "venue": "bithumb",
                            "canonical": canonical,
                            "listed": True,
                            "market_pair": f"{canonical}_KRW",
                            "krw_bid": buy,
                            "krw_ask": sell,
                            "krw_mid": mid,
                            "normalized_price_usd": mid / usdkrw,
                            "turnover_24h_krw": float(tick["acc_trade_value_24H"]) if tick.get("acc_trade_value_24H") else None,
                            "fx_rate": usdkrw,
                            "fx_source": "exchangerate-api",
                            "source_time": time.time(),
                        })
            except Exception:  # noqa: BLE001
                pass
        return korea_rows
    except Exception as e:  # noqa: BLE001
        log.warning(f"_korea_markets({canonical}) failed: {e}")
        return []

async def _global_market_cap(canonical: str) -> dict:
    """CoinGecko 市值+流通量（免费 50 calls/min）。"""
    try:
        import httpx
        # CoinGecko ID 映射（A3 简化版：常见币种硬编码；A5 完善为完整映射表）
        cg_id_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana",
            "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "AVAX": "avalanche-2",
            "MATIC": "matic-network", "DOT": "polkadot", "UNI": "uniswap", "LINK": "chainlink",
            "PEPE": "pepe", "SHIB": "shiba-inu", "ARB": "arbitrum", "OP": "optimism",
        }
        cg_id = cg_id_map.get(canonical)
        if not cg_id:
            return {}
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&community_data=false&developer_data=false")
            r.raise_for_status()
            data = r.json()
            mkt = data.get("market_data", {})
            return {
                "reported_market_cap_usd": mkt.get("market_cap", {}).get("usd"),
                "circulating_supply": mkt.get("circulating_supply"),
                "total_supply": mkt.get("total_supply"),
                "max_supply": mkt.get("max_supply"),
                "cg_id": cg_id,
                "source": "coingecko",
                "source_time": time.time(),
            }
    except Exception as e:  # noqa: BLE001
        log.warning(f"_global_market_cap({canonical}) failed: {e}")
        return {}

async def build_asset360_snapshot(canonical: str) -> dict:
    """Asset360Snapshot 单币全景快照（§4契约）。
    A1阶段：身份映射+六所价格/资金费（复用REV4基建）；24h量/OI留后续批次。
    A2：充提网络状态；A3：韩国市场+市值。"""
    snapshot_id = f"a360_{canonical}_{int(time.time())}"
    generated_at = datetime.now(timezone.utc).isoformat()
    # 并行拉六所市场
    venue_tasks = [_venue_markets(v, canonical) for v in _VENUES]
    venue_rows = await asyncio.gather(*venue_tasks, return_exceptions=True)
    venue_rows = [r for r in venue_rows if isinstance(r, dict)]  # 过滤异常
    # A2: 并行拉六所网络充提（当前占位，A2开工后补实际采集）
    network_tasks = [_venue_networks(v, canonical) for v in _VENUES]
    network_results = await asyncio.gather(*network_tasks, return_exceptions=True)
    network_rows = []
    for nets in network_results:
        if isinstance(nets, list):
            network_rows.extend(nets)
    # A3: 韩国市场+市值
    korea_rows = await _korea_markets(canonical)
    market_cap_data = await _global_market_cap(canonical)
    # 全局摘要（A3 补充市值、参考价）
    ref_price = None
    if venue_rows:
        marks = [v["perp_mark"]["value"] for v in venue_rows if v["perp_mark"]["value"]]
        if marks:
            marks_sorted = sorted(marks)
            ref_price = marks_sorted[len(marks_sorted) // 2]
    global_summary = {
        "reported_market_cap_usd": _mv(market_cap_data.get("reported_market_cap_usd"),
                                       "PRESENT" if market_cap_data.get("reported_market_cap_usd") else "NOT_CONNECTED",
                                       market_cap_data.get("source"), market_cap_data.get("source_time"), "USD"),
        "circulating_supply": _mv(market_cap_data.get("circulating_supply"),
                                 "PRESENT" if market_cap_data.get("circulating_supply") else "NOT_CONNECTED",
                                 market_cap_data.get("source"), market_cap_data.get("source_time")),
        "reference_spot_price_usd": _mv(ref_price, "PRESENT" if ref_price else "NOT_CONNECTED",
                                       "six_venue_median", generated_at, "USD"),
        "all_venue_oi_usd": _mv(None, "NOT_CONNECTED", None, None, "USD"),
        "listed_venue_count": _mv(len(venue_rows), "PRESENT", "snapshot", generated_at),
        "korea_listed_count": _mv(len(korea_rows), "PRESENT", "snapshot", generated_at),
    }
    return {
        "schema_version": "asset360-v1",
        "snapshot_id": snapshot_id,
        "asset_id": canonical,
        "canonical_symbol": canonical,
        "mapping_version": "alias-v1",
        "generated_at": generated_at,
        "global_summary": global_summary,
        "venue_rows": venue_rows,
        "network_rows": network_rows,  # A2: 逐网络充提状态
        "korea_rows": [],    # A3
        "korea_rows": [],    # A3
        "quality_summary": {"coverage_pct": round(100 * len(venue_rows) / len(_VENUES), 1)},
    }

# ══ 搜索 ═══════════════════════════════════════════════════════════════════
_COMMON_ASSETS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "MATIC", "DOT",
    "LINK", "UNI", "ATOM", "LTC", "ETC", "XLM", "ALGO", "FIL", "AAVE", "SAND",
    "MANA", "AXS", "GALA", "APE", "OP", "ARB", "PEPE", "SHIB", "FLOKI", "WLD",
    "SUI", "TIA", "SEI", "INJ", "PYTH", "JUP", "STRK", "ORDI", "SATS", "RATS",
]  # A1 预置白名单；A3 接 CoinGecko /coins/list 后移除硬编码

def search_assets(q: str, limit: int = 20) -> list[dict]:
    """搜索资产（当前阶段用预置列表+别名；后续接CoinGecko /coins/list）。"""
    q_norm = _norm_sym(q)
    results = []
    seen = set()
    # 搜规范symbol
    for canon in _COMMON_ASSETS:
        if q_norm in _norm_sym(canon):
            if canon not in seen:
                results.append({
                    "asset_id": canon, "canonical_symbol": canon,
                    "name": canon, "identity_status": "VERIFIED"})
                seen.add(canon)
    # 搜别名
    for canon, aliases in _KNOWN_ALIASES.items():
        for a in aliases:
            if q_norm in _norm_sym(a) and canon not in seen:
                results.append({
                    "asset_id": canon, "canonical_symbol": canon,
                    "name": f"{canon} (别名:{a})", "identity_status": "VERIFIED"})
                seen.add(canon)
                break
    return results[:limit]
