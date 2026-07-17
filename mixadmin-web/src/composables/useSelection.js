// V6.2 selection 分层(P0 Foundations 规约):
//   URL   = {wi(work_item_id), view, tab, f(filters紧凑串)} —— 可分享深链,语义状态
//   session = {scroll, expanded, colw, drawerw}            —— 会话恢复,不污染 URL
// 返回后筛选/选中行/展开状态恢复 = 终验硬指标。
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export function useSelection(pageKey) {
  const route = useRoute()
  const router = useRouter()
  const sk = `v62sel:${pageKey}`

  // ── URL 层 ──
  const wi = ref(String(route.query.wi || ''))
  const view = ref(String(route.query.view || ''))
  const tab = ref(String(route.query.tab || ''))
  const filters = ref(_decodeF(String(route.query.f || '')))

  let syncing = false
  function _push() {
    if (syncing) return
    const q = { ...route.query }
    wi.value ? (q.wi = wi.value) : delete q.wi
    view.value ? (q.view = view.value) : delete q.view
    tab.value ? (q.tab = tab.value) : delete q.tab
    const f = _encodeF(filters.value)
    f ? (q.f = f) : delete q.f
    router.replace({ query: q }).catch(() => {})
  }
  watch([wi, view, tab, filters], _push, { deep: true })
  // 浏览器返回/前进 → 恢复语义状态
  watch(() => route.query, (q) => {
    syncing = true
    wi.value = String(q.wi || ''); view.value = String(q.view || '')
    tab.value = String(q.tab || ''); filters.value = _decodeF(String(q.f || ''))
    syncing = false
  })

  // ── session 层 ──
  function _load() {
    try { return JSON.parse(sessionStorage.getItem(sk) || '{}') } catch { return {} }
  }
  const sess = ref(_load())
  function remember(patch) {
    sess.value = { ...sess.value, ...patch }
    try { sessionStorage.setItem(sk, JSON.stringify(sess.value)) } catch { /* 配额满不致命 */ }
  }
  /** 滚动记忆:绑定到滚动容器 el */
  function bindScroll(el) {
    if (!el) return
    if (sess.value.scroll) el.scrollTop = sess.value.scroll
    el.addEventListener('scroll', () => remember({ scroll: el.scrollTop }), { passive: true })
  }
  return { wi, view, tab, filters, sess, remember, bindScroll }
}

function _encodeF(f) {
  const parts = Object.entries(f || {}).filter(([, v]) => v).map(([k, v]) => `${k}:${v}`)
  return parts.join(',')
}
function _decodeF(s) {
  const out = {}
  for (const p of (s || '').split(',')) {
    const i = p.indexOf(':')
    if (i > 0) out[p.slice(0, i)] = p.slice(i + 1)
  }
  return out
}
