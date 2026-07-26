/**
 * HustleCoin Mix — 币种主行 / ↳子账户子行 数据契约（两级，无卡片层）
 *
 * 铁律：
 * 1. phase 直接渲染后端仲裁契约的状态码，前端绝不推断状态
 *    （历史教训：采信 HTTP200 致单腿盲、僵尸假运行）。
 * 2. 排序键用后端字段（opened_at / pnl），不解析前端渲染值。
 * 3. 手工干预是异常态低频操作 —— 全部收进右键菜单（+ 行尾 ⋮ / 移动端长按），
 *    不占常驻屏幕面积；1:1 对齐 coin.hustle2026.xyz/dashboard。
 * 4. 子行显示的是【执行账户】：hedge_via_master 场景对冲腿挂平台主账号，
 *    是主账号显示主账号、是子账户显示子账户，accountKind 徽章区分，前端不按名义归属推断。
 */

export type StrategyCode = 'C1' | 'C2.H' | 'C2.C' | 'C2.P' | 'C3.S' | 'C3.R' | 'C4' | 'C5' | 'C6' | 'O1' | 'S1' | 'S2' | 'S3' | 'S4' | 'S5' | 'S6'

/** 账户平台类型 —— 账户列表与 KMS 钱包并表的开关：操作菜单按此注入 */
export type PlatformType = 'cex' | 'kms_wallet'

/** 状态机阶段 —— 与后端仲裁契约枚举一一对应，UI 不新增值 */
export type PhaseCode =
  | 'CANDIDATE' | 'ARBITRATING' | 'ARMED' | 'OPENING' | 'HOLDING' | 'EXITING' | 'SETTLED'
  | 'BORROWABLE' | 'PENDING_BORROW' | 'REPAYING' | 'COOLDOWN_3045' | 'FROZEN'
  | 'QUOTA_CHECK' | 'LENDING' | 'ACCRUING' | 'RECLAIMING'
  | 'EVENT_FEED' | 'EVALUATING' | 'MANUAL_CONFIRM' | 'REVERTING'

export interface StrategyMeta {
  /** V5 产品编号(C1-C6/C2.H等;S6=O1运营能力非C目录) */
  ccode?: string
  code: StrategyCode
  name: string
  color: string
  colorBg: string
  icon: string // lucide
}

export const STRATEGY_META: Record<StrategyCode, StrategyMeta> = {
  // C系列10产品（V6产品体系）
  C1: { code: 'C1', ccode: 'C1', name: '期现收费', color: '#4A9CFF', colorBg: 'rgba(74,156,255,.12)', icon: 'scale' },
  'C2.H': { code: 'C2.H', ccode: 'C2.H', name: '跨所费差', color: '#F0B90B', colorBg: 'rgba(240,185,11,.12)', icon: 'layers' },
  'C2.C': { code: 'C2.C', ccode: 'C2.C', name: '事件折价', color: '#FF9F43', colorBg: 'rgba(255,159,67,.12)', icon: 'zap' },
  'C2.P': { code: 'C2.P', ccode: 'C2.P', name: '人工研判', color: '#8B5CF6', colorBg: 'rgba(139,92,246,.12)', icon: 'user-check' },
  'C3.S': { code: 'C3.S', ccode: 'C3.S', name: '借币点差', color: '#A78BFA', colorBg: 'rgba(167,139,250,.12)', icon: 'rotate-ccw' },
  'C3.R': { code: 'C3.R', ccode: 'C3.R', name: '三率利差', color: '#2DD4BF', colorBg: 'rgba(45,212,191,.12)', icon: 'hand-coins' },
  C4: { code: 'C4', ccode: 'C4', name: '期现交割', color: '#10B981', colorBg: 'rgba(16,185,129,.12)', icon: 'calendar-check' },
  C5: { code: 'C5', ccode: 'C5', name: '双永续', color: '#EC4899', colorBg: 'rgba(236,72,153,.12)', icon: 'repeat' },
  C6: { code: 'C6', ccode: 'C6', name: '双交割', color: '#06B6D4', colorBg: 'rgba(6,182,212,.12)', icon: 'calendar-days' },
  O1: { code: 'O1', ccode: 'O1', name: '做量降费', color: '#F472B6', colorBg: 'rgba(244,114,182,.12)', icon: 'orbit' },
  // S系列兼容映射（向后兼容旧数据）
  S1: { code: 'S1', ccode: 'C1', name: '期现收费', color: '#4A9CFF', colorBg: 'rgba(74,156,255,.12)', icon: 'scale' },
  S2: { code: 'S2', ccode: 'C2.H', name: '跨所费差', color: '#F0B90B', colorBg: 'rgba(240,185,11,.12)', icon: 'layers' },
  S3: { code: 'S3', ccode: 'C3.S', name: '借币点差', color: '#A78BFA', colorBg: 'rgba(167,139,250,.12)', icon: 'rotate-ccw' },
  S4: { code: 'S4', ccode: 'C3.R', name: '三率利差', color: '#2DD4BF', colorBg: 'rgba(45,212,191,.12)', icon: 'hand-coins' },
  S5: { code: 'S5', ccode: 'C2.C', name: '事件折价', color: '#FF9F43', colorBg: 'rgba(255,159,67,.12)', icon: 'zap' },
  S6: { code: 'S6', ccode: 'O1', name: '做量降费', color: '#F472B6', colorBg: 'rgba(244,114,182,.12)', icon: 'orbit' },
}

/**
 * 关键设计（coinmini 同款）：币种行兼列头 —— 同一列位在两类行里语义/取数完全不同。
 * 币种行在数值列位上渲染【文字标签】（现-期/爆率/最大可借…），子账户行渲染【真实数值】。
 * 标签跟着行走，长表滚动无需回看表头；混合策略平铺时每行自带本策略的列标签。
 */
export interface CellValue {
  value: string
  tone?: 'up' | 'down' | 'muted' | 'accent' | 'strategy'
  /** <1U 粉尘弱化显示 */
  dim?: boolean
}

/** 参数块小对（币种行=行情参数：开/平/资/时/限/息；子行=持仓经济：润/资/开/息/累息/平，未借到留空） */
export interface ParamPair { label: string; value: string; tone?: CellValue['tone'] }

/** 子账户行三态互斥状态（同一列位复用） */
export type SubRowState =
  | { kind: 'api_error'; text: string }                      // 红
  | { kind: 'borrowing'; text: string }                      // 青
  | { kind: 'repay_paused'; text: string; resumable: true }  // 金，可点恢复
  | { kind: 'holding'; text: string }                        // 持仓时长
  | { kind: 'plain'; text: string }

/** ↳ 子账户子行 —— 该币种在单个【执行账户】上的真实数值 */
export interface AccountSubRow {
  /** 执行账户；hedge_via_master 下 现-期/爆率 取主账户合约（全表同值），
   *  现币/借币/风险/保证金/净值 取该子账户杠杆户自己的 */
  executingAccount: string
  accountKind: 'master' | 'sub'
  venue: string
  platformType: PlatformType
  /** 与币种行 columnLabels 一一对齐（S3 口径：现-期=主合约持仓币数、爆率=维持保证金率%、
   *  最大可借=VIP 档 borrow_limit、现币=sm.free、借币=sm.borrowed 实时本金、
   *  借币金额=borrowed×spot_bid、风险=marginLevel、保证金=净资产含 BNB、净值=可用纯 U） */
  values: CellValue[]
  /** 持仓经济：润(已实现+资金费−利息)/资(累计资金费)/开(开仓点差)/息(日利率)/累息/平；未借到 null */
  econParams: ParamPair[] | null
  state: SubRowState
  /** 该持仓资息倍率 funding_rate_ratio */
  fundingRateRatio: string | null
  /** 每秒可借次数（按该账户 UID 权重余量，各账户不同） */
  borrowRatePerSec: string | null
  /** 借币封禁倒计时 M:SS；无则 null */
  banCountdown: string | null
  /** 账户级"被币安 API 限制"红字（复用规则列位） */
  apiRestricted: boolean
  apiStatus: 'ok' | 'restricted' | 'healing'
}

/** 币种主行 —— 汇总 + 兼列头 */
export interface PositionRow {
  id: string
  symbol: string
  /** ×持仓数；0 = 无持仓（展开钮显 ·） */
  positionCount: number
  /** 退市/死币 💀 标红；风险币 ⚠ */
  mark?: 'dead' | 'risk'
  strategyCode: StrategyCode
  phase: PhaseCode
  phaseLabel: string           // 后端下发中文标签
  /** 本行数值列的标签集（按策略注入，与子行 values 同列位对齐） */
  columnLabels: string[]
  /** 行情参数块：开(可开点差)/平(可平点差)/资(资金费率)/时(结算周期)/限(费率上限)/息(日利率) */
  marketParams: ParamPair[]
  /** 紧凑态运行状态，否则 "推 时间"/"已推" */
  pushStatus: string
  /** 资息倍率（费率倍率，负=成本） */
  fundingRateRatio: string
  /** 单一规则简写（开X 平Y）或 '-' */
  singleRuleBrief: string
  /** 移/还可用性（禁用标红） */
  allowRemove: boolean
  allowRepay: boolean
  pnl: number | null
  openedAt: string | null      // ISO — 排序键
  keyDeadlineTs: number | null // <30min 整行左→右渐变转黄
  /** 通用规则=继承策略模板；单一规则=存在币种覆盖（金色，可点设置） */
  ruleScope: 'template' | 'override'
  subRows: AccountSubRow[]
}

/** 右键菜单项（右键 / 行尾 ⋮ / 移动端长按 三入口同一菜单） */
export interface MenuItem {
  key: string
  label: string
  icon: string                // lucide
  kind?: 'normal' | 'danger' | 'strategy' | 'link'
  /** 在此项上方画分隔线 */
  dividerBefore?: boolean
  /** danger 项强制二次确认浮层 */
  confirm?: boolean
}

export type SortKey = 'opened_at' | 'pnl'
export type SortDir = 'asc' | 'desc'
