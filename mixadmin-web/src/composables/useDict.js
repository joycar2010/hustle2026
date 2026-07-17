// V6.1 §6.1 术语字典消费:默认显示业务标签,悬停/专家详情显示原始代码。
// 全站单例缓存;取不到字典时如实回落原码(绝不编造翻译)。
import { ref } from 'vue'
import { mixApi } from '../api/mix'

const dict = ref(null)
let loading = null

export function useDict() {
  if (!dict.value && !loading) {
    loading = mixApi.v6Dictionary().then(d => { dict.value = d || {} })
      .catch(() => { dict.value = {} })
  }
  /** 业务标签(找不到=原码) */
  function term(code) { return dict.value?.[code]?.label || code }
  /** 悬停解释 */
  function explain(code) { return dict.value?.[code]?.explain || '' }
  /** 标签(原码) 双显 */
  function full(code) {
    const t = term(code)
    return t === code ? code : `${t}`
  }
  return { dict, term, explain, full }
}

// DataValueState(§6.2) 渲染口径:真0/未接入/待产生/过期/核对中 视觉可区分
export const DV_CN = {
  PRESENT: null, ZERO: null,
  NOT_APPLICABLE: '—',
  NOT_CONNECTED: '未接入',
  NOT_YET_AVAILABLE: '待产生',
  STALE: '已过期',
  UNDER_REVIEW: '核对中',
  ERROR: '暂不可得',
}
export function dvText(value, state, fmt = (v) => v) {
  if (state === 'PRESENT' || state === 'ZERO' || value != null) return fmt(value)
  return DV_CN[state] || '未接入'
}
export function dvClass(state) {
  return { NOT_CONNECTED: 'dv-nc', NOT_YET_AVAILABLE: 'dv-wait', STALE: 'dv-stale',
           UNDER_REVIEW: 'dv-review', ERROR: 'dv-err', NOT_APPLICABLE: 'dv-na' }[state] || ''
}
