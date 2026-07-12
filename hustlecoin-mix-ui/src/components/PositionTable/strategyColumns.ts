/**
 * 列 schema 与右键菜单注入 —— 按 strategy_code / platformType 注入。
 *
 * 结构 = 公共前缀列 + 策略插槽列(≤6) + 公共后缀列（参数/推送/PnL/行内高频钮/⋮/规则）。
 * 全自动系统的手工干预全部收进右键菜单；行内只留 coin dashboard 验证过的
 * 高频文字钮（S3 的 移/还）+ ⋮ 显式入口（右键的可发现性兜底）。
 */
import type { ColumnDef, MenuItem, PlatformType, StrategyCode } from './types'

export interface ColumnDef { key: string; label: string; width?: number; align?: 'left' | 'right' }

/* ---------------- 主行策略插槽列 ---------------- */
const MAIN_SLOTS: Record<StrategyCode, ColumnDef[]> = {
  S1: [
    { key: 'spot_perp', label: '现-期' }, { key: 'basis', label: '当前基差' },
    { key: 'basis_apr', label: '基差年化' }, { key: 'funding_recv', label: '已收资金费' },
    { key: 'margin_ratio', label: '保证金率' },
  ],
  S2: [
    { key: 'rate_diff', label: '费率差' }, { key: 'next_settle', label: '下次结费' },
    { key: 'delta', label: 'Delta' }, { key: 'funding_recv', label: '已收资金费' },
    { key: 'liq_dist', label: '距强平' },
  ],
  S3: [ // 1:1 coin dashboard
    { key: 'spot_perp', label: '现-期' }, { key: 'burst', label: '爆率' },
    { key: 'max_borrow', label: '最大可借' }, { key: 'funding_recv', label: '已收费率' },
    { key: 'borrow_apr', label: '息率' },
  ],
  S4: [
    { key: 'rate_spread', label: '年化利差' }, { key: 'term_left', label: '借期剩余' },
    { key: 'interest_recv', label: '已收利息' }, { key: 'principal', label: '本金' },
    { key: 'pool_util', label: '池利用率' },
  ],
  S5: [
    { key: 'discount', label: '折价深度' }, { key: 'target', label: '回归目标' },
    { key: 'reverted', label: '已回归' }, { key: 'expect', label: '预期剩余' },
    { key: 'deadpool', label: '死池校验' },
  ],
  S6: [
    { key: 'quota', label: '日目标量' }, { key: 'done', label: '已完成' },
    { key: 'maker_ratio', label: 'maker 占比' }, { key: 'rebate', label: '当日返佣' },
    { key: 'spread_cost', label: '点差损耗' },
  ],
}

/* ---------------- ↳子账户子行插槽列（执行账户明细） ---------------- */
const SUB_SLOTS: Record<StrategyCode, ColumnDef[]> = {
  S1: [
    { key: 'spot_qty', label: '现货' }, { key: 'perp_qty', label: '永续空' },
    { key: 'avg_px', label: '开仓均价' }, { key: 'margin', label: '保证金' }, { key: 'risk', label: '风险' },
  ],
  S2: [
    { key: 'side', label: '方向' }, { key: 'qty', label: '数量' }, { key: 'avg_px', label: '均价' },
    { key: 'margin', label: '保证金' }, { key: 'risk', label: '风险' }, { key: 'adl', label: 'ADL' },
  ],
  S3: [ // 1:1 coin dashboard 子账户行
    { key: 'max_borrow', label: '最大可借' }, { key: 'spot_bal', label: '现币' },
    { key: 'borrowed', label: '借币' }, { key: 'risk', label: '风险' },
    { key: 'margin', label: '保证金' }, { key: 'int_cnt', label: '息' },
  ],
  S4: [
    { key: 'rate', label: '利率' }, { key: 'amount', label: '数量' }, { key: 'interest', label: '利息' },
    { key: 'quota_left', label: '额度余' }, { key: 'risk', label: '风险' },
  ],
  S5: [
    { key: 'spot_qty', label: '现货' }, { key: 'hedge_qty', label: '对冲空' },
    { key: 'avg_disc', label: '折价均价' }, { key: 'margin', label: '保证金' }, { key: 'risk', label: '风险' },
  ],
  S6: [
    { key: 'orders', label: '挂单' }, { key: 'filled', label: '成交' },
    { key: 'self_trade', label: '自成交拦截' }, { key: 'rebate_tier', label: '返佣档' }, { key: 'sched', label: '时段' },
  ],
}

/* ---------------- 行内高频文字钮（coin 原样，其余全进菜单） ---------------- */
export const INLINE_ACTIONS: Record<StrategyCode, Array<{ key: string; label: string }>> = {
  S1: [{ key: 'close', label: '平' }],
  S2: [{ key: 'close', label: '平' }],
  S3: [{ key: 'move', label: '移' }, { key: 'repay', label: '还' }],
  S4: [{ key: 'reclaim', label: '收' }],
  S5: [{ key: 'confirm', label: '确认' }],
  S6: [{ key: 'quota', label: '调目标' }],
}

/* ---------------- 右键菜单（右键 / ⋮ / 长按 同源） ---------------- */
export const CONTEXT_MENUS: Record<StrategyCode, MenuItem[]> = {
  S3: [
    { key: 'add_order', label: '补单', icon: 'plus' },
    { key: 'add_hedge', label: '补对冲', icon: 'shuffle' },
    { key: 'rule_override', label: '单独规则…', icon: 'scroll-text', kind: 'link', dividerBefore: true },
    { key: 'blacklist', label: '移入黑名单', icon: 'ban' },
    { key: 'manual_repay', label: '手动还币', icon: 'rotate-ccw', kind: 'strategy', dividerBefore: true, confirm: true },
    { key: 'force_close', label: '强制平仓', icon: 'octagon-x', kind: 'danger', confirm: true },
  ],
  S2: [
    { key: 'add_order', label: '补单', icon: 'plus' },
    { key: 'add_hedge', label: '补对冲', icon: 'shuffle' },
    { key: 'rebuild_leg', label: '单腿重建', icon: 'wrench', dividerBefore: true, confirm: true },
    { key: 'rule_override', label: '单独规则…', icon: 'scroll-text', kind: 'link' },
    { key: 'blacklist', label: '移入黑名单', icon: 'ban' },
    { key: 'force_close', label: '强制平仓', icon: 'octagon-x', kind: 'danger', dividerBefore: true, confirm: true },
  ],
  S1: [
    { key: 'add_order', label: '补单', icon: 'plus' },
    { key: 'close_spot', label: '平现货腿', icon: 'coins', dividerBefore: true, confirm: true },
    { key: 'close_perp', label: '平永续腿', icon: 'trending-down', confirm: true },
    { key: 'rule_override', label: '单独规则…', icon: 'scroll-text', kind: 'link', dividerBefore: true },
    { key: 'force_close', label: '整体平仓', icon: 'octagon-x', kind: 'danger', confirm: true },
  ],
  S4: [
    { key: 'renew', label: '续期', icon: 'calendar-plus' },
    { key: 'early_reclaim', label: '提前回收', icon: 'undo-2', confirm: true },
    { key: 'transfer_out', label: '转出', icon: 'arrow-left-right', dividerBefore: true },
    { key: 'rule_override', label: '单独规则…', icon: 'scroll-text', kind: 'link' },
  ],
  S5: [
    { key: 'confirm_enter', label: '确认介入', icon: 'check', kind: 'strategy', confirm: true },
    { key: 'abandon', label: '放弃回归', icon: 'x', dividerBefore: true },
    { key: 'force_exit', label: '立即离场', icon: 'octagon-x', kind: 'danger', confirm: true },
  ],
  S6: [
    { key: 'quota', label: '调整目标量', icon: 'sliders-horizontal' },
    { key: 'schedule', label: '切换时段分布', icon: 'clock' },
    { key: 'pause', label: '暂停刷量', icon: 'octagon-pause', kind: 'danger', dividerBefore: true, confirm: true },
  ],
}

/* ---------------- 账户列表菜单（按 platformType 注入；KMS 行换钱包管理模块） ---------------- */
export const ACCOUNT_MENUS: Record<PlatformType, MenuItem[]> = {
  cex: [
    { key: 'create_sub', label: '新建子账户', icon: 'plus' },
    { key: 'toggle', label: '启用 / 禁用', icon: 'power' },
    { key: 'verify', label: '验证 API 连通', icon: 'badge-check' },
    { key: 'refresh', label: '刷新余额', icon: 'refresh-cw' },
    { key: 'ip_whitelist', label: 'IP 白名单…', icon: 'shield', kind: 'link', dividerBefore: true },
    { key: 'ip_proxy', label: 'IP 代理…', icon: 'globe', kind: 'link' },
    { key: 'set_api', label: '设置 API…', icon: 'key-round', kind: 'link' },
    { key: 'purge', label: '清除', icon: 'eraser', kind: 'danger', dividerBefore: true, confirm: true },
  ],
  kms_wallet: [ // KMS 钱包管理模块：发起/审批分离 + 白名单 + 限额铁律不因并表放松
    { key: 'create_wallet', label: '创建钱包（KMS 内生成）', icon: 'plus' },
    { key: 'addr_whitelist', label: '地址白名单…', icon: 'shield', kind: 'link' },
    { key: 'transfer', label: '发起转账（需审批）', icon: 'send', kind: 'strategy', confirm: true },
    { key: 'audit', label: '签名审计日志', icon: 'scroll-text', kind: 'link', dividerBefore: true },
    { key: 'freeze', label: '紧急冻结', icon: 'snowflake', kind: 'danger', dividerBefore: true, confirm: true },
  ],
}

export function getMainColumns(code: StrategyCode): ColumnDef[] { return MAIN_SLOTS[code] }
export function getSubColumns(code: StrategyCode): ColumnDef[] { return SUB_SLOTS[code] }
