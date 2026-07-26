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

# 全仓/逐仓能力静态表(交易所永续保证金模式支持,稳定事实,零API调用)
# 六所主流永续均同时支持 cross+isolated;HL 只有 cross(逐仓叫 isolated margin 但按仓,标 both)
_MARGIN_CAP = {
    "binance": {"cross": True, "isolated": True},
    "okx": {"cross": True, "isolated": True},
    "bybit": {"cross": True, "isolated": True},
    "gate": {"cross": True, "isolated": True},
    "bitget": {"cross": True, "isolated": True},
    "hyperliquid": {"cross": True, "isolated": True},
}


async def _margin_modes(venue: str, canonical: str) -> dict:
    return _MARGIN_CAP.get(venue, {})


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
    # 无持仓且 funding feed 无 mark(如 okx)→ 回落 L1 中价
    if mark_price is None and r:
        try:
            l1raw = await r.hget(f"dcm:feed:{venue}:perp", canonical + "USDT")
            if l1raw:
                l1 = json.loads(l1raw)
                b, a = float(l1.get("bid") or 0), float(l1.get("ask") or 0)
                if b > 0 and a > 0:
                    mark_price = round((b + a) / 2, 8)
        except Exception:  # noqa: BLE001
            pass
    # OI:oi_feed 多所采集(60s缓存,失败=None 诚实)
    oi_usd = None
    try:
        from . import oi_feed
        oi = await oi_feed.get_oi(venue, canonical + "USDT", mark_price)
        oi_usd = oi.get("oi_usdt")
    except Exception:  # noqa: BLE001
        pass
    # 一档盘口(l1lite 按需WS订阅;首次点击后数秒建订,miss=订阅建立中;HL无现货=不适用)
    async def _l1(market):
        if venue == "hyperliquid" and market == "spot":
            return {"state": "NOT_APPLICABLE"}
        try:
            raw = await r.get(f"dcm:l1lite:{venue}:{market}:{canonical}") if r else None
            if not raw:
                return {"state": "NOT_CONNECTED", "reason": "SUBSCRIBING"}
            d = json.loads(raw)
            bid, ask = d.get("bid"), d.get("ask")
            mid = (bid + ask) / 2 if bid and ask else None
            # 张→base换算已下沉到 l1lite 发布端(乘数经 dcm:l1lite:mult hash),此处不再二次乘
            bq = d.get("bq") or 0
            aq = d.get("aq") or 0
            return {"state": "PRESENT", "bid": bid, "ask": ask,
                    "spread_bps": round((ask - bid) / mid * 10000, 2) if mid else None,
                    "bid_usdt": round(bq * bid, 0) if bid else None,
                    "ask_usdt": round(aq * ask, 0) if ask else None,
                    "ts": d.get("ts")}
        except Exception:  # noqa: BLE001
            return {"state": "ERROR"}
    spot_l1 = await _l1("spot")
    perp_l1 = await _l1("perp")
    # 24h成交量(l1lite ticker帧,USDT口径);现货无=—
    async def _vol(market):
        try:
            raw = await r.get(f"dcm:l1lite:vol:{venue}:{market}:{canonical}") if r else None
            if raw:
                return json.loads(raw).get("vol_usdt")
        except Exception:  # noqa: BLE001
            pass
        return None
    spot_vol = await _vol("spot")
    perp_vol = await _vol("perp")
    # 全仓/逐仓能力(I1 instrument_spec position_mode;缺=六所永续几乎皆支持双模式,标 UNKNOWN)
    cross_iso = await _margin_modes(venue, canonical)
    # 充提通道状态(B机 io-monitor 采集,dcm:cex:io:{venue} hash;HL无=NOT_APPLICABLE)
    dep_st = wd_st = None
    if venue == "hyperliquid":
        dep_st = wd_st = "NOT_APPLICABLE"
    else:
        try:
            ioraw = await r.hget(f"dcm:cex:io:{venue}", canonical) if r else None
            if ioraw:
                io = json.loads(ioraw)
                dep_st, wd_st = io.get("dep"), io.get("wd")
        except Exception:  # noqa: BLE001
            pass
    return {
        "venue": venue,
        "canonical": canonical,
        "spot_l1": spot_l1,
        "perp_l1": perp_l1,
        "spot_vol_24h_usd": _mv(spot_vol, "PRESENT" if spot_vol else "NOT_CONNECTED", f"vol:{venue}", now_ts, "USD"),
        "perp_vol_24h_usd": _mv(perp_vol, "PRESENT" if perp_vol else "NOT_CONNECTED", f"vol:{venue}", now_ts, "USD"),
        "has_cross": _mv(cross_iso.get("cross"), "PRESENT" if cross_iso.get("cross") is not None else "UNKNOWN", "instrument_spec", now_ts),
        "has_isolated": _mv(cross_iso.get("isolated"), "PRESENT" if cross_iso.get("isolated") is not None else "UNKNOWN", "instrument_spec", now_ts),
        "deposit_status": _mv(dep_st, "PRESENT" if dep_st in ("OPEN", "CLOSED") else ("NOT_APPLICABLE" if dep_st == "NOT_APPLICABLE" else "NOT_CONNECTED"), f"io:{venue}", now_ts),
        "withdraw_status": _mv(wd_st, "PRESENT" if wd_st in ("OPEN", "CLOSED") else ("NOT_APPLICABLE" if wd_st == "NOT_APPLICABLE" else "NOT_CONNECTED"), f"io:{venue}", now_ts),
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
        "oi_usd": _mv(oi_usd, "PRESENT" if oi_usd else "NOT_CONNECTED", f"oi:{venue}", now_ts, "USD"),
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


_cg_search_cache: dict = {}


async def _cg_search_id(canonical: str):
    """CoinGecko /search 按symbol动态解析id(硬编码表只有16币的"流通市值未接入"根因);
    24h缓存含负缓存;取symbol精确匹配里rank最高者。"""
    hit = _cg_search_cache.get(canonical)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    cid = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as cli:
            r = await cli.get("https://api.coingecko.com/api/v3/search", params={"query": canonical})
            coins = [c for c in (r.json().get("coins") or [])
                     if str(c.get("symbol", "")).upper() == canonical]
            coins.sort(key=lambda c: c.get("market_cap_rank") or 10**9)
            if coins:
                cid = coins[0].get("id")
    except Exception:  # noqa: BLE001
        pass
    _cg_search_cache[canonical] = (time.time(), cid)
    return cid

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
            cg_id = await _cg_search_id(canonical)
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

_ct_mult_cache: dict = {}


async def _ct_mult(venue: str, canonical: str) -> float:
    """张→base 乘数(gate=quanto_multiplier/okx=ctVal,存 instrument_spec.contract_multiplier),
    1h 缓存,查不到=1(§7.1 铁律:张数不换算直接×价=虚高百倍,okx BTC 1张=0.01)。"""
    key = (venue, canonical)
    hit = _ct_mult_cache.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    m = 1.0
    try:
        pool = await ds.pg_main()
        if pool is not None:
            v = await pool.fetchval(
                "SELECT contract_multiplier FROM instrument_spec WHERE venue=$1 "
                "AND market_type='perp' AND canonical_underlying=$2 AND linear_or_inverse='linear' LIMIT 1",
                venue, canonical)
            if v:
                m = float(v)
    except Exception:  # noqa: BLE001
        pass
    _ct_mult_cache[key] = (time.time(), m)
    return m


async def l1lite_mult_loop():
    """为 l1lite 发布张→base乘数(gate/okx perp):HSET dcm:l1lite:mult "{venue}:{CANON}"=mult。
    l1lite 无PG,乘数权威=instrument_spec,由本loop按want集合每300s同步。"""
    await asyncio.sleep(20)
    while True:
        try:
            r = ds.rds()
            pool = await ds.pg_main()
            if r and pool is not None:
                wants = []
                async for k in r.scan_iter(match="dcm:l1lite:want:*", count=200):
                    wants.append(k.split(":")[-1])
                for canon in wants:
                    for venue in ("gate", "okx"):
                        m = await _ct_mult(venue, canon)
                        await r.hset("dcm:l1lite:mult", f"{venue}:{canon}", m)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(300)


async def build_asset360_snapshot(canonical: str) -> dict:
    """Asset360Snapshot 单币全景快照（§4契约）。
    A1阶段：身份映射+六所价格/资金费（复用REV4基建）；24h量/OI留后续批次。
    A2：充提网络状态；A3：韩国市场+市值。"""
    snapshot_id = f"a360_{canonical}_{int(time.time())}"
    generated_at = datetime.now(timezone.utc).isoformat()
    # 登记 l1lite 按需订阅(want 键 TTL 900s;服务 5s 内建订,闲置 15min 自动退订)
    try:
        r0 = ds.rds()
        if r0:
            await r0.setex(f"dcm:l1lite:want:{canonical}", 900, "1")
    except Exception:  # noqa: BLE001
        pass
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
        "all_venue_oi_usd": _mv(
            (lambda s: round(s, 0) if s else None)(
                sum(v["oi_usd"]["value"] or 0 for v in venue_rows)),
            "PRESENT" if any(v["oi_usd"]["value"] for v in venue_rows) else "NOT_CONNECTED",
            "oi_feed(6venues)", generated_at, "USD"),
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
        "korea_rows": korea_rows,  # A3(修:此前键重复被空数组覆盖,算了白算)
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
