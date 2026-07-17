"""
Pydantic 模型 —— 与 contracts/openapi.yaml components 一一对应，
也与前端 hustlecoin-mix-ui/src/components/PositionTable/types.ts 逐字段对齐。
关键：币种行兼列头（columnLabels 是标签、子行 values 是数值，同列位）；
子账户行下发 executingAccount + accountKind（hedge_via_master 显主账号）。
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field
from .enums import StrategyCode, PhaseCode, PlatformType, AccountKind, CoinState

Tone = Literal["up", "down", "muted", "accent", "strategy"]


class CellValue(BaseModel):
    value: str
    tone: Optional[Tone] = None
    dim: bool = False  # <1U 粉尘弱化


class ParamPair(BaseModel):
    label: str
    value: str
    tone: Optional[Tone] = None


class SubRowState(BaseModel):
    kind: Literal["api_error", "borrowing", "repay_paused", "holding", "plain"]
    text: str
    resumable: Optional[bool] = None  # 仅 repay_paused=True 时出现


class AccountSubRow(BaseModel):
    executingAccount: str  # hedge_via_master 下为平台主账号
    accountKind: AccountKind
    venue: str
    platformType: PlatformType
    # 与主行 columnLabels 一一对齐；S3 口径：
    # 现-期=主合约持仓 / 爆率=维持保证金率% / 最大可借=VIP borrow_limit /
    # 现币=sm.free / 借币=sm.borrowed 实时本金 / 借币金额=borrowed×spot_bid /
    # 风险=marginLevel / 保证金=净资产含BNB / 净值=可用纯U
    values: list[CellValue]
    econParams: Optional[list[ParamPair]] = None  # 未借到为 None
    state: SubRowState
    fundingRateRatio: Optional[str] = None
    borrowRatePerSec: Optional[str] = None  # 每账户 UID 权重余量不同
    banCountdown: Optional[str] = None       # "M:SS"
    apiRestricted: bool = False
    apiStatus: Literal["ok", "restricted", "healing"] = "ok"


class PositionRow(BaseModel):
    id: str
    symbol: str
    positionCount: int
    mark: Optional[Literal["dead", "risk"]] = None
    strategyCode: StrategyCode
    phase: PhaseCode
    phaseLabel: str
    columnLabels: list[str]        # 币种行兼列头（按策略注入）
    marketParams: list[ParamPair]  # 开/平/资/时/限/息
    pushStatus: str
    fundingRateRatio: str
    singleRuleBrief: str
    allowRemove: bool
    allowRepay: bool
    pnl: Optional[float] = None
    openedAt: Optional[str] = None      # ISO — 排序键
    keyDeadlineTs: Optional[int] = None  # epoch ms，距今<30min 前端整行渐变
    ruleScope: Literal["template", "override"]
    subRows: list[AccountSubRow] = Field(default_factory=list)


class PositionAction(BaseModel):
    action: str                     # 见 CONTEXT_MENUS key
    accountId: Optional[str] = None  # 子账户行操作时必传
    idempotencyKey: Optional[str] = None


class AccountNode(BaseModel):
    id: str
    kind: AccountKind
    platformType: PlatformType
    venue: str
    domain: str  # 域 A/B/C / 链上
    apiStatus: Literal["ok", "restricted", "healing"]
    metrics: dict[str, str]
    # 余额七维(资金/现货/合约/理财/杠杆可用/借入/风险值);None=未接入,前端显 —(§6.2 缺值契约)
    bal: Optional[dict] = None
    approvalState: Optional[str] = None  # KMS 审批流状态
    children: list["AccountNode"] = Field(default_factory=list)


class AccountCreate(BaseModel):
    kind: Literal["master", "sub"]  # 新建必选
    venue: str
    parentId: Optional[str] = None  # sub 时挂载主账户


class RuleField(BaseModel):
    key: str
    label: str
    value: str
    unit: Optional[str] = None
    type: Optional[Literal["switch", "enum"]] = None
    options: Optional[list[str]] = None
    inherited: bool = False
    locked: bool = False  # S5 人工确认 / S6 自成交拦截 强制


class RulesResponse(BaseModel):
    scope: str
    fields: list[RuleField]
    uniqueRow: bool = True  # 每作用域唯一行 + 唯一索引


class KmsTransfer(BaseModel):
    from_wallet: str = Field(alias="from")
    to_address: str
    ccy: str
    amount: float


class CoinRow(BaseModel):
    symbol: str
    state: CoinState
    strategies: list[StrategyCode]
    venues: str
    rate8h: str
    spreadBps: Optional[float] = None
    vol24h: str
    managed: int


class NotifySettings(BaseModel):
    channels: list[str]
    intervalSec: int
    maxPerHour: int
    cooldownSec: int
    tokenBucket: dict  # {rate, burst}
