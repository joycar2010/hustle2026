"""CROSSARB_ 前缀的环境配置(与生产 CEX_ 前缀零交集)。

读取顺序:进程环境变量 > 同目录 .env > 内置默认。
不依赖 pydantic,保持零额外依赖。
"""
import os
from pathlib import Path


def _load_dotenv() -> None:
    # 极简 .env 加载:仅当变量尚未在环境中时才填充
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


def _get(name: str, default: str) -> str:
    # 容忍行内 # 注释:systemd EnvironmentFile 与 .env 都不剥离注释,
    # 若值里带 "...  # 说明" 会污染 float()/int() 解析,这里统一剥离。
    v = os.environ.get(name, default)
    if isinstance(v, str) and "#" in v:
        v = v.split("#", 1)[0]
    return v.strip() if isinstance(v, str) else v


class Config:
    base_rpc: str = _get("CROSSARB_BASE_RPC", "https://mainnet.base.org")
    binance_fapi: str = _get("CROSSARB_BINANCE_FAPI", "https://fapi.binance.com")
    binance_symbol: str = _get("CROSSARB_BINANCE_SYMBOL", "ETHUSDT")

    fee_tier: int = int(_get("CROSSARB_FEE_TIER", "500"))
    notional_usd: float = float(_get("CROSSARB_NOTIONAL_USD", "2500"))

    taker_fee_bps: float = float(_get("CROSSARB_TAKER_FEE_BPS", "4.5"))
    gas_units: int = int(_get("CROSSARB_GAS_UNITS", "150000"))
    l1_fee_usd: float = float(_get("CROSSARB_L1_FEE_USD", "0.05"))
    recycle_bps: float = float(_get("CROSSARB_RECYCLE_BPS", "0"))

    min_net_bps: float = float(_get("CROSSARB_MIN_NET_BPS", "20"))
    poll_sec: float = float(_get("CROSSARB_POLL_SEC", "5"))
    # 并行报价并发度。公共 RPC(mainnet.base.org)严格限频,建议 1-2;
    # Alchemy/QuickNode 端点可放到 8+。默认 2 求稳。
    rpc_concurrency: int = int(_get("CROSSARB_RPC_CONCURRENCY", "2"))

    csv_path: str = _get("CROSSARB_CSV", "./data/ticks.csv")
    http_host: str = _get("CROSSARB_HTTP_HOST", "127.0.0.1")  # nginx 在前,默认只听本机
    http_port: int = int(_get("CROSSARB_HTTP_PORT", "8100"))
    redis_url: str = _get("CROSSARB_REDIS_URL", "")

    # 飞书每日播报(自建应用):app_id/secret + 收件人;留空则不发
    # 收件人优先用 email(与应用无关,不踩 open_id 跨应用问题),否则用 open_id
    feishu_app_id: str = _get("CROSSARB_FEISHU_APP_ID", "")
    feishu_app_secret: str = _get("CROSSARB_FEISHU_APP_SECRET", "")
    feishu_open_id: str = _get("CROSSARB_FEISHU_OPEN_ID", "")
    feishu_email: str = _get("CROSSARB_FEISHU_EMAIL", "")


cfg = Config()
