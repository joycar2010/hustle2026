// 全站公共枚举字典 — 收口"呈现给操作员的裸英文枚举"。
// 用法:import { zh } from '../dicts'; zh(USER_STATUS, row.status)  → 中文,未知值兜底原值。
export const USER_STATUS = { active:'正常', trial:'试用', expired:'过期', banned:'封禁', disabled:'停用' }
export const AUTO_MODE   = { off:'关', shadow:'影子', armed:'武装', full:'全量' }
export const AUTO_MODE_SHORT = { off:'关', shadow:'影', armed:'武', full:'全' }
export const ORDER_STATUS = { paid:'已支付', pending:'待支付', refunded:'已退款', failed:'失败', void:'已作废' }
export const RECONCILE_STATUS = { pending:'待核对', confirmed:'已确认', discrepancy:'差异', void:'已作废' }
export const ORDER_KIND = { iap:'内购', recharge:'充值', subscription:'订阅', manual:'手工', gift:'赠送' }
export const GRANT_SOURCE = { iap:'内购', manual:'手工', gift:'赠送' }
export const ACCOUNT_ROLE = { main:'主腿', hedge:'对冲腿', master:'主账户' }
export const LEAD_STATUS = { new:'新线索', contacted:'已联系', trial:'试用中', converted:'已转化', lost:'已流失' }
export const CHANNEL_FIELD = { token:'校验令牌', appid:'应用ID', secret:'应用密钥', aeskey:'消息加密密钥' }

// 通用查表:未命中返回原值(保证不吞未知枚举)
export function zh(dict, key){ if(key==null) return '—'; return dict[key] != null ? dict[key] : String(key) }
// tag 类型映射(element-plus el-tag type)
export const USER_STATUS_TAG = { active:'success', trial:'warning', expired:'info', banned:'danger', disabled:'info' }
export const ORDER_STATUS_TAG = { paid:'success', pending:'warning', refunded:'info', failed:'danger', void:'info' }
export const RECONCILE_TAG = { pending:'info', confirmed:'success', discrepancy:'danger', void:'info' }
export const LEAD_STATUS_TAG = { new:'warning', contacted:'primary', trial:'', converted:'success', lost:'info' }
