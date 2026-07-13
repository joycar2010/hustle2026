"""
状态枚举单一来源（Single Source of Truth）。
契约铁律 #1：前端绝不推断状态，一律渲染后端下发的 phase；
/meta/enums 直接序列化本文件，前端启动先拉取再渲染。
仲裁契约（arbitration contract）变更状态机时，只改这里。
"""
from enum import Enum


class StrategyCode(str, Enum):
    S1 = "S1"  # 期现收费(单所期现对冲收资金费)
    S2 = "S2"  # 跨所费差(双合约跨所资金费率差)
    S3 = "S3"  # 借币点差(借币做空·现-期点差,coin 引擎)
    S4 = "S4"  # 三率利差(资金费+理财-借币利率净差)
    S5 = "S5"  # 事件折价(事件窗口+LST/锚定折价回归)
    S6 = "S6"  # 做量降费(交易量提VIP档降费率飞轮)


class PhaseCode(str, Enum):
    # 通用
    CANDIDATE = "CANDIDATE"
    ARBITRATING = "ARBITRATING"
    ARMED = "ARMED"
    OPENING = "OPENING"
    HOLDING = "HOLDING"
    EXITING = "EXITING"
    SETTLED = "SETTLED"
    # S3 借币反向
    BORROWABLE = "BORROWABLE"
    PENDING_BORROW = "PENDING_BORROW"
    REPAYING = "REPAYING"
    COOLDOWN_3045 = "COOLDOWN_3045"
    FROZEN = "FROZEN"
    # S4 借贷
    QUOTA_CHECK = "QUOTA_CHECK"
    LENDING = "LENDING"
    ACCRUING = "ACCRUING"
    RECLAIMING = "RECLAIMING"
    # S5 事件
    EVENT_FEED = "EVENT_FEED"
    EVALUATING = "EVALUATING"
    MANUAL_CONFIRM = "MANUAL_CONFIRM"
    REVERTING = "REVERTING"


class AlertLevel(str, Enum):
    FATAL = "FATAL"
    WARN = "WARN"
    INFO = "INFO"


class SubRowStateKind(str, Enum):
    api_error = "api_error"        # 红：账户级 API 异常
    borrowing = "borrowing"        # 青：借币中
    repay_paused = "repay_paused"  # 金：还币暂停，可点恢复
    holding = "holding"            # 持仓时长
    plain = "plain"


class PlatformType(str, Enum):
    cex = "cex"
    kms_wallet = "kms_wallet"


class AccountKind(str, Enum):
    master = "master"
    sub = "sub"
    wallet = "wallet"


class CoinState(str, Enum):
    enabled = "enabled"
    watch = "watch"
    paused = "paused"
    frozen = "frozen"      # 风控态：仅人工核对裸空后解冻
    delisted = "delisted"


def enums_payload() -> dict:
    """GET /meta/enums —— 前端渲染依赖这一份。"""
    return {
        "StrategyCode": [e.value for e in StrategyCode],
        "PhaseCode": [e.value for e in PhaseCode],
        "AlertLevel": [e.value for e in AlertLevel],
        "SubRowStateKind": [e.value for e in SubRowStateKind],
        "PlatformType": [e.value for e in PlatformType],
        "CoinState": [e.value for e in CoinState],
    }
