"""
运行配置 —— 全部来自环境变量（systemd EnvironmentFile=/data/mix/backend/.env）。
mix-backend 是读聚合 + 写代理层：
  - MIX_PG_DSN    : dcm_main 只读角色 mix_ro（绝不用 dcm 主角色 —— 本服务无权写引擎库）
  - MIX_REDIS_URL : A 机 dcm 总线（与 dcm 服务同源）
未配置时进入 degraded 模式：接口可用但数据为空并带 degraded 标记，绝不 500 也绝不编数据。
"""
import os

PG_DSN = os.environ.get("MIX_PG_DSN", "")
REDIS_URL = os.environ.get("MIX_REDIS_URL", "")

# 只读令牌（VIEWER 级）；操作员令牌走 dcm_main.operators 表 sha256 校验
READONLY_TOKEN = os.environ.get("MIX_READONLY_TOKEN", "")

# mix 自有库（用户体系/KMS 审批流）—— mix_app 角色，读写；与 dcm_main(mix_ro 只读)分库隔离爆炸半径
MAIN_DSN = os.environ.get("MIX_MAIN_DSN", "")
# 用户端 JWT（HS256）；未配置则用户端登录不可用（operator 令牌不受影响）
JWT_SECRET = os.environ.get("MIX_JWT_SECRET", "")
JWT_TTL_HOURS = int(os.environ.get("MIX_JWT_TTL_HOURS", "24"))

# 心跳阈值（秒）—— 对齐 risk-ledger EXPECTED_HB 口径，未列出的用 default
HB_EXPECTED = {
    "feed-cex": 120, "coin-bridge": 240, "universe-sync": 7500, "gateway": 120,
    "engine-dualperp": 120, "engine-basis": 120, "risk-ledger": 120,
    "decision": 300, "funding-sync": 600, "carry-advisor": 1900,
    "account-snapshot": 300, "depth-sampler": 4000, "basis-sampler": 300,
    "pnl-recorder": 900, "lending-advisor": 1900, "llm-advisor": 2000,
    "fund-scheduler": 7500, "event-calendar": 900, "borrow-monitor": 600,
    "transfer-monitor": 900, "engine-lending": 1400,
}
HB_DEFAULT_SEC = 900

CACHE_TTL_SEC = float(os.environ.get("MIX_CACHE_TTL_SEC", "3"))
