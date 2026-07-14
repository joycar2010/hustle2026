<template>
  <div class="riskbar" :class="{ stale: d.stale }">
    <!-- 行1:平台模式章(文字+色,V5 §14 禁止只用颜色)+ 版本 + 冻结新增 -->
    <div class="r1">
      <span class="modechip" :class="modeCls(d.worst_mode)">
        平台模式 {{ d.worst_mode || 'STALE' }}<i v-if="d.worst_mode==='NORMAL'">·已核验</i>
        <i v-else-if="d.stale">·数据超龄 fail-closed</i>
      </span>
      <span class="kv">策略权威 <b>e{{ d.policy_epoch ?? '—' }}·v{{ d.policy_version ?? '—' }}</b></span>
      <span class="kv">新鲜度 <b :class="{bad: d.stale}">{{ d.age_sec == null ? 'N/A' : d.age_sec + 's' }}</b></span>
      <span class="kv" v-if="d.top_incident">最高Incident
        <b class="bad">{{ d.top_incident.venue }}·{{ d.top_incident.title }}</b></span>
      <span class="grow" />
      <el-button size="small" type="danger" plain @click="freezeAll">冻结新增风险</el-button>
      <el-link class="more" @click="$router.push('/mix/venuerisk')">平台风险工作台 →</el-link>
    </div>
    <!-- 行2:风险摘要七项(V5 §14.1) + 受限venue文字告示 -->
    <div class="r2">
      <span class="item">受限账户 <b :class="{bad: d.restricted_accounts>0}">{{ n(d.restricted_accounts) }}</b></span>
      <span class="item">受限权益 <b :class="{bad: d.restricted_equity_usdt>0}">{{ n(d.restricted_equity_usdt) }}U</b></span>
      <span class="item">风险调整可用权益 <b>{{ n(d.nav?.available_equity_usdt) }}U</b></span>
      <span class="item">NAV折价 <b :class="{bad: (d.nav?.trapped_usdt||0)>0}">{{ n(d.nav?.trapped_usdt) }}U</b></span>
      <span class="item">最老pending提现 <b :class="{bad: (d.oldest_pending?.age_sec||0)>21600}">
        {{ d.oldest_pending?.age_sec ? fmtAge(d.oldest_pending.age_sec) + '·' + d.oldest_pending.venue : '无' }}</b></span>
      <span class="item">24h提现成功率 <b>{{ d.wd_24h?.rate == null ? 'N/A(无样本)' : d.wd_24h.rate + '%' }}</b></span>
      <span class="item">未复核条款 <b :class="{warn2: (d.unreviewed_terms||[]).length>0}">{{ (d.unreviewed_terms||[]).length }}</b></span>
      <span v-if="notice" class="notice" :class="modeCls(notice.mode)">
        {{ notice.venue }} · {{ notice.mode }} — {{ short(notice.reason) }} · 暴露 {{ n(notice.equity) }}U · 新开仓已禁止
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../api/mix'

const d = ref({ stale: true })
let timer = null
const SEV = { FROZEN: 6, QUARANTINED: 6, EXIT_ONLY: 5, REDUCE_ONLY: 4, NO_NEW_RISK: 3 }
const notice = computed(() => {
  const vs = (d.value.venues || []).filter(v => SEV[v.mode])
  return vs.length ? vs[0] : null
})
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
const short = s => String(s || '').split('|')[0].slice(0, 42)
const fmtAge = s => (s >= 3600 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 60) + 'm')
const modeCls = m => ({
  NORMAL: 'ok', WATCH: 'watch', NO_NEW_RISK: 'nonew', REDUCE_ONLY: 'red',
  EXIT_ONLY: 'red', FROZEN: 'quar', QUARANTINED: 'quar', RECOVERY_WATCH: 'recov',
}[m] || 'unknown')

async function load() { try { d.value = await mixApi.riskSummary() } catch (e) { d.value = { stale: true } } }
async function freezeAll() {
  try {
    await ElMessageBox.confirm('对全局追加 NO_NEW_RISK 覆盖(减险动作,立即生效;恢复须显式 NORMAL 覆盖+审计)?', '冻结新增风险', { type: 'warning', confirmButtonText: '冻结' })
    await mixApi.riskOverrideAdd({ scope_type: 'GLOBAL', scope_key: 'GLOBAL', mode: 'NO_NEW_RISK', reason: '操作员手动冻结(状态条)' })
    ElMessage.success('已追加全局 NO_NEW_RISK,risk-ledger ≤30s 合并生效')
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '失败') }
}
onMounted(() => { load(); timer = setInterval(load, 10000) })
onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped lang="scss">
/* V5 §14.7 模式色规范:NORMAL低饱和绿/WATCH黄/NO_NEW橙#FF8A3D/REDUCE·EXIT红/
   QUARANTINED深红#8B1E2D/RECOVERY蓝灰#8CA3C7/STALE灰 fail-closed;全部配文字 */
.riskbar { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  border-radius: 8px; padding: 6px 12px; display: flex; flex-direction: column; gap: 4px;
  &.stale { border-color: #5E6673; }
}
.r1, .r2 { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; font-size: 11.5px; color: var(--mix-t2, #848E9C); }
.grow { flex: 1; }
.modechip { font-weight: 800; font-size: 12px; padding: 2px 10px; border-radius: 5px;
  i { font-style: normal; font-weight: 500; opacity: .85; }
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.watch { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.nonew { background: rgba(255,138,61,.16); color: #FF8A3D; }
  &.red { background: rgba(246,70,93,.16); color: #F6465D; }
  &.quar { background: #8B1E2D; color: #fff; }
  &.recov { background: rgba(140,163,199,.16); color: #8CA3C7; }
  &.unknown { background: rgba(94,102,115,.2); color: #9aa4b2; } }
.kv b, .item b { color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums;
  &.bad { color: #F6465D; } &.warn2 { color: #F0B90B; } }
.notice { margin-left: auto; font-weight: 700; padding: 2px 10px; border-radius: 5px; max-width: 46%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.more { font-size: 11.5px; }
</style>
