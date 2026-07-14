<template>
  <div class="vrisk">
    <RiskStatusBar />
    <!-- 主表:严重度降序(QUARANTINED→…→NORMAL),正常折叠异常上浮(V5 §14.2) -->
    <div class="card">
      <div class="chd">平台与账户风险工作台
        <span class="legend">七模式:<i class="lg quar">QUARANTINED 资金/交易访问受限</i><i class="lg red">EXIT_ONLY 按计划退出</i>
          <i class="lg red">REDUCE_ONLY 仅减仓</i><i class="lg nonew">NO_NEW_RISK 禁止新增</i>
          <i class="lg watch">WATCH 弱信号</i><i class="lg recov">RECOVERY 阶梯恢复</i><i class="lg ok">NORMAL 已核验</i></span>
        <el-checkbox v-model="showNormal" size="small">显示正常平台</el-checkbox>
      </div>
      <el-table :data="rowsShown" size="small" :row-class-name="rowCls">
        <el-table-column label="Venue" width="96"><template #default="{row}"><b class="vn link" @click="$router.push('/mix/venue/'+row.venue)">{{ row.venue }}</b>
          <i class="tier" v-if="row.tier">Tier {{ row.tier }}</i></template></el-table-column>
        <el-table-column label="有效模式" width="130"><template #default="{row}">
          <span class="mch" :class="modeCls(row.mode)">{{ row.mode }}</span></template></el-table-column>
        <el-table-column label="Incident态" width="86"><template #default="{row}">{{ row.incident_state || 'N/A' }}</template></el-table-column>
        <el-table-column label="恢复阶梯" width="96"><template #default="{row}">
          {{ row.recovery ? `阶段${row.recovery.stage}·${Math.round(row.recovery.allow_pct*100)}%` : '—' }}</template></el-table-column>
        <el-table-column label="权益U" width="86" align="right"><template #default="{row}">{{ n(row.equity) }}</template></el-table-column>
        <el-table-column label="敞口U" width="80" align="right"><template #default="{row}">{{ n(row.exposure_notional) }}</template></el-table-column>
        <el-table-column label="上限U" width="80" align="right"><template #default="{row}">{{ n(row.cap_usdt) }}</template></el-table-column>
        <el-table-column label="折价/受限U" width="96" align="right"><template #default="{row}">
          <span :class="{bad: row.trapped_usdt>0}">{{ row.haircut_pct ? (row.haircut_pct*100)+'% / '+n(row.trapped_usdt) : '—' }}</span></template></el-table-column>
        <el-table-column label="提现健康" min-width="150"><template #default="{row}">
          <template v-if="row.withdrawal">pending {{ row.withdrawal.pending_count }}
            · p95 {{ row.withdrawal.p95_sec ? Math.round(row.withdrawal.p95_sec/60)+'m' : 'N/A' }}
            <span v-if="row.withdrawal.recent_failures" class="bad">· 失败{{ row.withdrawal.recent_failures }}</span></template>
          <template v-else><span class="dim">N/A(未接/键过期)</span></template></template></el-table-column>
        <el-table-column label="原因(命中作用域)" min-width="220"><template #default="{row}">
          <span class="rsn" :title="row.reason">{{ hitText(row) }}</span></template></el-table-column>
        <el-table-column label="动作" width="120" fixed="right"><template #default="{row}">
          <el-link type="warning" @click="freezeVenue(row.venue)" v-if="!SEV[row.mode]">冻结新增</el-link>
          <span v-else class="dim">已受限</span>
        </template></el-table-column>
      </el-table>
      <div class="fnote">允许动作=查看事实/冻结新增/工单/标记审核/证据包/已批准收敛;禁止重复提现、换IP重试、切换未登记账户(V5 §14.4)。
        提高风险/恢复NORMAL 须 override 显式 NORMAL+审计(逐级恢复阶梯强制)。</div>
    </div>

    <div class="grid2">
      <!-- 活跃 Incident(有状态:OPEN/ESCALATED/RECOVERING) -->
      <div class="card">
        <div class="chd">活跃 Incident <b :class="{bad: incidents.length}">{{ incidents.length }}</b></div>
        <div v-if="!incidents.length" class="dim pad">无活跃事件</div>
        <div v-for="i in incidents" :key="i.venue + i.rule" class="inc">
          <span class="mch" :class="i.severity==='fatal' ? 'red' : 'watch'">{{ i.state }}</span>
          <b>{{ i.venue }}</b> · {{ i.title }}
          <span class="dim">命中{{ i.hit_count }}次 · 持续{{ fmtAge(i.age_sec) }}</span>
          <div class="incd">{{ i.detail }}</div>
        </div>
      </div>
      <!-- 模式历史(before/after/原因,恢复审计) -->
      <div class="card">
        <div class="chd">模式转变历史(近20)</div>
        <div v-if="!transitions.length" class="dim pad">无记录</div>
        <div v-for="(t, i) in transitions" :key="i" class="tr">
          <b>{{ t.venue }}</b>
          <span class="mch sm" :class="modeCls(t.before_mode)">{{ t.before_mode }}</span>→
          <span class="mch sm" :class="modeCls(t.after_mode)">{{ t.after_mode }}</span>
          <span class="dim">{{ String(t.reason||'').split('|')[0].slice(0,36) }} · {{ (t.recorded_at||'').slice(5,16) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const d = ref({})
const showNormal = ref(false)
let timer = null
const SEV = { FROZEN: 1, QUARANTINED: 1, EXIT_ONLY: 1, REDUCE_ONLY: 1, NO_NEW_RISK: 1 }
// 正常平台可折叠,异常永远上浮;全绿时不给空表(全部显示)
const rowsShown = computed(() => {
  const rows = d.value.venues || []
  if (showNormal.value || rows.every(r => r.mode === 'NORMAL')) return rows
  return rows.filter(r => r.mode !== 'NORMAL')
})
const incidents = computed(() => d.value.incidents || [])
const transitions = computed(() => d.value.transitions || [])
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
const fmtAge = s => (s >= 3600 ? Math.floor(s / 3600) + 'h' : Math.floor((s || 0) / 60) + 'm')
const modeCls = m => ({ NORMAL: 'ok', WATCH: 'watch', NO_NEW_RISK: 'nonew', REDUCE_ONLY: 'red',
  EXIT_ONLY: 'red', FROZEN: 'quar', QUARANTINED: 'quar', RECOVERY_WATCH: 'recov' }[m] || 'unknown')
const rowCls = ({ row }) => (SEV[row.mode] ? 'sev-row' : '')
const hitText = row => {
  const hs = row.modes_hit || []
  if (!hs.length) return row.mode === 'NORMAL' ? 'ok' : String(row.reason || '').split('|')[0]
  return hs.map(h => `${h.scope}→${h.mode}${h.why ? '(' + String(h.why).slice(0, 26) + ')' : ''}`).join(' · ')
}
async function load() { try { d.value = await mixApi.riskSummary() } catch (e) { /* 状态条已示 STALE */ } }
async function freezeVenue(v) {
  try {
    await ElMessageBox.confirm(`对 ${v} 追加 NO_NEW_RISK 覆盖(减险,立即)?`, '冻结该venue新增', { type: 'warning' })
    await mixApi.riskOverrideAdd({ scope_type: 'VENUE', scope_key: v, mode: 'NO_NEW_RISK', reason: '操作员冻结(风险工作台)' })
    ElMessage.success(`已追加 ${v} NO_NEW_RISK`)
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '失败') }
}
onMounted(() => { load(); timer = setInterval(load, 10000) })
onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped lang="scss">
.vrisk { display: flex; flex-direction: column; gap: 10px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; }
.chd { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  b.bad { color: #F6465D; } }
.legend { display: flex; gap: 6px; flex-wrap: wrap; font-weight: 400; }
.lg { font-style: normal; font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.mch { font-weight: 800; font-size: 10.5px; padding: 1px 8px; border-radius: 4px; &.sm { font-size: 9.5px; padding: 0 5px; } }
.mch, .lg {
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.watch { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.nonew { background: rgba(255,138,61,.16); color: #FF8A3D; }
  &.red { background: rgba(246,70,93,.16); color: #F6465D; }
  &.quar { background: #8B1E2D; color: #fff; }
  &.recov { background: rgba(140,163,199,.16); color: #8CA3C7; }
  &.unknown { background: rgba(94,102,115,.2); color: #9aa4b2; } }
.vn { color: var(--mix-t1, #EAECEF); &.link { cursor: pointer; &:hover { color: #F0B90B; } } }
.tier { font-style: normal; margin-left: 6px; font-size: 9px; color: var(--mix-t3, #5E6673); }
.bad { color: #F6465D; } .dim { color: var(--mix-t3, #5E6673); } .pad { padding: 8px 0; }
.rsn { font-size: 10.5px; }
:deep(.sev-row) { background: rgba(246,70,93,.05); }
.fnote { font-size: 10px; color: var(--mix-t3, #5E6673); margin-top: 8px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.inc { font-size: 11.5px; color: var(--mix-t2, #848E9C); padding: 5px 0; border-bottom: 1px dashed var(--mix-border, #262B33);
  b { color: var(--mix-t1, #EAECEF); } }
.incd { font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-top: 2px; }
.tr { font-size: 11px; color: var(--mix-t2, #848E9C); padding: 3px 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
  b { color: var(--mix-t1, #EAECEF); min-width: 60px; } }
</style>
