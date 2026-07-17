// V6 统一快照消费(§4):首次 REST 全量 → WS control:snapshot 帧(generation 增量)触发刷新;
// 断连保留最后快照并置 stale;快照 as_of 超 90s = 过期,禁止新增风险(fail-closed)。
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { mixApi } from '../api/mix'
import { connectStream } from '../api/mixWs'

// 调用者角色(模块级缓存,一次 whoami 全站共享)——VIEWER/普通用户对"新增风险"类按钮降级为不可点,
// 与服务端 workitems 的 allowed_actions 降级同一语义(2026-07-16:test 用户点「送入工作台」被 401 踢出事故)
const _role = ref('')
let _roleLoaded = false
async function _loadRole() {
  if (_roleLoaded) return
  _roleLoaded = true
  try { const w = await mixApi.whoami(); _role.value = w?.role || 'VIEWER' }
  catch (e) { _role.value = 'VIEWER'; _roleLoaded = false }  // 失败按只读兜底,下次重试
}

export function useV6Snapshot() {
  const snap = ref(null)
  const wsOn = ref(false)
  const lastFrameAt = ref(0)
  let stopWs = null
  let poll = null
  let refetching = false

  async function refetch() {
    if (refetching) return
    refetching = true
    try { snap.value = await mixApi.v6Snapshot() } catch (e) { /* 保留最后快照,靠 stale 标注 */ }
    refetching = false
  }

  const stale = computed(() => {
    if (!snap.value) return true
    const t = Date.parse(snap.value.as_of || 0)
    return !t || (Date.now() - t) > 90000
  })
  // 风险能力永远覆盖运行方式:过期/受限=隐藏新增风险动作,保留减险
  const canOpen = computed(() => !stale.value && !!snap.value?.effective_capabilities?.can_open)
  // 角色维度(与系统能力分离:状态条仍显示系统 canOpen,按钮叠加角色)
  const isOperator = computed(() => _role.value === 'OPERATOR' || _role.value === 'SUPER_ADMIN')
  const ago = computed(() => {
    if (!snap.value) return 'N/A'
    const s = (Date.now() - Date.parse(snap.value.as_of)) / 1000
    return s < 60 ? `${s.toFixed(1)}s 前` : `${Math.floor(s / 60)}m 前`
  })

  onMounted(() => {
    refetch()
    _loadRole()
    stopWs = connectStream((m) => {
      wsOn.value = true
      if (m.channel === 'control:snapshot') {
        lastFrameAt.value = Date.now()
        // generation 跳号(漏帧/hub重启)=旧状态不可拼补丁,强制全量重拉(PATCH-02 §4.2)
        const skipped = snap.value && m.generation != null && m.generation > (snap.value.generation ?? 0) + 1
        if (m.changed || skipped) refetch()
        else if (snap.value && m.generation === snap.value.generation) {
          // 心跳帧:只推 as_of,免整包重拉
          snap.value = { ...snap.value, as_of: m.as_of }
        }
      }
    })
    poll = setInterval(refetch, 30000)  // WS 兜底轮询
  })
  onBeforeUnmount(() => { stopWs && stopWs(); clearInterval(poll) })

  return { snap, stale, canOpen, isOperator, ago, wsOn, refetch }
}
