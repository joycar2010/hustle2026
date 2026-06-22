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
    exit_floor_bps: float = float(_get("CROSSARB_EXIT_FLOOR_BPS", "5"))  # 退出滑点下限(深币聚合器报~0时兜底,保守)

    min_net_bps: float = float(_get("CROSSARB_MIN_NET_BPS", "20"))
    poll_sec: float = float(_get("CROSSARB_POLL_SEC", "5"))
    # 深度探测:沿名义额阶梯找滑点≤容忍线的最大可执行额(spec 3.3/5.1 可执行量)
    depth_ladder: str = _get("CROSSARB_DEPTH_LADDER", "1000,2500,5000,10000")
    depth_slip_tol_bps: float = float(_get("CROSSARB_DEPTH_SLIP_TOL_BPS", "30"))  # 可执行额的滑点容忍线
    depth_every_n: int = int(_get("CROSSARB_DEPTH_EVERY_N", "4"))  # 每 N 拍才探测1个市场(降聚合器负载)
    # 并行报价并发度。公共 RPC(mainnet.base.org)严格限频,建议 1-2;
    # Alchemy/QuickNode 端点可放到 8+。默认 2 求稳。
    rpc_concurrency: int = int(_get("CROSSARB_RPC_CONCURRENCY", "2"))
    kyber_client_id: str = _get("CROSSARB_KYBER_CLIENT_ID", "crossarb")  # 聚合器 x-client-id
    kyber_min_interval: float = float(_get("CROSSARB_KYBER_MIN_INTERVAL", "0.16"))  # 聚合器请求最小间隔(秒),防429

    csv_path: str = _get("CROSSARB_CSV", "./data/ticks.csv")
    http_host: str = _get("CROSSARB_HTTP_HOST", "127.0.0.1")  # nginx 在前,默认只听本机
    http_port: int = int(_get("CROSSARB_HTTP_PORT", "8100"))
    redis_url: str = _get("CROSSARB_REDIS_URL", "")

    # ===== P1 执行验证(最小,OP单链$500)=====
    # 三档:dry-run(默认,只模拟不下单)| testnet(币安测试网真下单+链上模拟)| live(真金)
    exec_mode: str = _get("CROSSARB_EXEC_MODE", "dry-run")
    exec_market: str = _get("CROSSARB_EXEC_MARKET", "OP:BTC")     # 只做这一个市场
    exec_notional_usd: float = float(_get("CROSSARB_EXEC_NOTIONAL_USD", "500"))
    exec_min_net_bps: float = float(_get("CROSSARB_EXEC_MIN_NET_BPS", "25"))  # 触发执行的净基差(高于看板20,留安全垫)
    exec_poll_sec: float = float(_get("CROSSARB_EXEC_POLL_SEC", "3"))
    # 币安做空腿凭证(独立账户!绝不用生产coin账户)
    bn_api_key: str = _get("CROSSARB_BN_API_KEY", "")
    bn_api_secret: str = _get("CROSSARB_BN_API_SECRET", "")
    # 熔断
    exec_max_trades: int = int(_get("CROSSARB_EXEC_MAX_TRADES", "20"))        # 总单数上限
    exec_max_daily_usd: float = float(_get("CROSSARB_EXEC_MAX_DAILY_USD", "3000"))  # 单日链上支出上限
    exec_naked_timeout_sec: float = float(_get("CROSSARB_EXEC_NAKED_TIMEOUT_SEC", "20"))  # 裸腿超时强平
    # 链上签名(live才用):KMS key id;dry-run/testnet留空
    exec_kms_key_id: str = _get("CROSSARB_EXEC_KMS_KEY_ID", "")
    exec_wallet_addr: str = _get("CROSSARB_EXEC_WALLET_ADDR", "")  # 钱包地址(KyberSwap build calldata 需 sender)
    exec_kms_region: str = _get("CROSSARB_EXEC_KMS_REGION", "ap-northeast-1")  # KMS 所在 region
    exec_rpc: str = _get("CROSSARB_EXEC_RPC", "https://mainnet.optimism.io")  # live 广播用链 RPC(建议换 Alchemy)
    exec_slippage_bps: int = int(_get("CROSSARB_EXEC_SLIPPAGE_BPS", "50"))  # swap 滑点容忍(编进calldata的minOut)
    exec_approve_cap_usd: float = float(_get("CROSSARB_EXEC_APPROVE_CAP_USD", "3000"))  # 单次授权额度上限(非无限授权)
    exec_recv_timeout_sec: float = float(_get("CROSSARB_EXEC_RECV_TIMEOUT_SEC", "120"))  # 等链上回执超时

    # 飞书每日播报(自建应用):app_id/secret + 收件人;留空则不发
    # 收件人优先用 email(与应用无关,不踩 open_id 跨应用问题),否则用 open_id
    feishu_app_id: str = _get("CROSSARB_FEISHU_APP_ID", "")
    feishu_app_secret: str = _get("CROSSARB_FEISHU_APP_SECRET", "")
    feishu_open_id: str = _get("CROSSARB_FEISHU_OPEN_ID", "")
    feishu_email: str = _get("CROSSARB_FEISHU_EMAIL", "")
    feishu_mobile: str = _get("CROSSARB_FEISHU_MOBILE", "")


cfg = Config()
