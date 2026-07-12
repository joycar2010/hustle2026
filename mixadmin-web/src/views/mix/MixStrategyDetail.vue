<template>
  <div class="sdetail" v-if="detail">
    <div class="hd">
      <span class="code" :style="{background:META[code].colorBg,color:META[code].color}">{{ code }}</span>
      <span class="name">{{ detail.layer }} · {{ detail.name }}</span>
      <span class="kpi"><em>坑位</em><b>{{ detail.slots || '—' }}</b></span>
      <span class="kpi"><em>今日</em><b class="up">+{{ detail.pnlToday }}</b></span>
      <span class="kpi"><em>累计</em><b class="up">+{{ (detail.pnlTotal||0).toLocaleString() }}</b></span>
      <el-button size="small" @click="$router.push('/mix/strategies')">返回总览</el-button>
    </div>

    <div class="pipe">
      <template v-for="(v,k,i) in detail.pipeline" :key="k">
        <span class="stage" :style="{borderColor:META[code].color+'44'}"><em>{{ k }}</em><b>{{ v }}</b></span>
        <span v-if="i < Object.keys(detail.pipeline).length-1" class="arr">›</span>
      </template>
    </div>

    <!-- 红线汇总（S3：画板"薄降/冻结/冷却"降维为三数；由真行 mark/状态推导） -->
    <div class="redline" v-if="code === 'S3'">
      <span class="rl bad">黑名单 {{ redline.black }}</span>
      <span class="rl warn">冷却中 {{ redline.cooldown }}</span>
      <span class="rl">可借候选 {{ redline.borrowable }}</span>
      <span class="rl dim">推送中·无券 {{ redline.noinv }}</span>
    </div>

    <VirtualPositionTable :rows="detail.rows||[]" sort-key="opened_at" sort-dir="asc" :height="420"
                          @action="onAction" @rule-override="onRule" />

    <div class="botcols">
      <div class="rules" v-if="rules">
        <b>{{ code }} 模板规则快照</b>
        <span v-for="f in rules.fields" :key="f.key" class="rf">
          {{ f.key }} = {{ f.value }}{{ f.unit||'' }} <i v-if="f.inherited">（继承）</i>
        </span>
        <el-link type="warning" @click="$router.push('/mix/rules')">去规则中心编辑模板 →</el-link>
      </div>
      <div class="salerts">
        <b>{{ code }} 策略告警</b>
        <div v-for="(a, i) in stratAlerts.slice(0, 6)" :key="i" class="sa-row">
          <span class="lv" :class="a.level.toLowerCase()">{{ a.level }}</span>
          <span class="sa-at">{{ a.at }}</span>
          <span class="sa-txt" :title="a.text">{{ a.text }}</span>
        </div>
        <span v-if="!stratAlerts.length" class="sa-empty">该策略暂无告警</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import VirtualPositionTable from '../../components/PositionTable/VirtualPositionTable.vue'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const route = useRoute()
const code = route.params.code
const detail = ref(null)
const rules = ref(null)
const stratAlerts = ref([])
const redline = computed(() => {
  const rows = detail.value?.rows || []
  return {
    black: rows.filter(r => r.mark === 'risk').length,
    cooldown: rows.filter(r => (r.subRows || []).some(s => s.banCountdown)).length,
    borrowable: rows.filter(r => r.phase === 'BORROWABLE').length,
    noinv: rows.filter(r => r.phase === 'CANDIDATE').length,
  }
})

async function onAction({ action, rowId, accountId }) {
  try {
    const r = await mixApi.positionAction(rowId, action, accountId)
    ElMessage.success(r?.note || '已受理')
  } catch (e) { ElMessage.error(e?.error || '被拒绝') }
}
function onRule(rowId) { ElMessageBox.alert(`币种覆盖：${rowId}（M3 接线）`, '单独规则') }

onMounted(async () => {
  detail.value = await mixApi.strategy(code)
  rules.value = await mixApi.rules(`strategy:${code}`)
  try { stratAlerts.value = await mixApi.alerts(code) } catch (e) { /* 降级 */ }
})
</script>

<style scoped lang="scss">
.sdetail { display: flex; flex-direction: column; gap: 10px; }
.hd { display: flex; align-items: center; gap: 14px;
  .code { padding: 3px 10px; border-radius: 8px; font-weight: 800; }
  .name { font-weight: 800; font-size: 15px; flex: 1; }
  .kpi { display: inline-flex; gap: 5px; align-items: baseline; font-size: 12px;
    em { font-style: normal; color: var(--el-text-color-secondary); } b { font-size: 14px; } }
  .up { color: #0ECB81; } }
.pipe { display: flex; gap: 6px; align-items: center; flex-wrap: wrap;
  .stage { border: 1px solid; border-radius: 7px; padding: 4px 10px; display: inline-flex; gap: 6px; align-items: baseline; font-size: 11px;
    em { font-style: normal; color: var(--el-text-color-secondary); font-size: 10px; } b { font-size: 14px; } }
  .arr { color: var(--el-text-color-placeholder); } }
.rules { font-size: 12px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; flex: 1;
  .rf { color: var(--el-text-color-regular); i { color: var(--el-text-color-placeholder); font-style: normal; } } }
.redline { display: flex; gap: 8px; font-size: 11.5px;
  .rl { border: 1px solid var(--mix-border, #262B33); border-radius: 6px; padding: 2px 9px; color: var(--mix-t2, #848E9C);
    &.bad { color: var(--mix-red, #F6465D); border-color: rgba(246,70,93,.4); }
    &.warn { color: var(--mix-accent, #F0B90B); border-color: rgba(240,185,11,.4); }
    &.dim { color: var(--mix-t3, #5E6673); } } }
.botcols { display: flex; gap: 16px; align-items: flex-start; }
.salerts { width: 380px; flex: none; font-size: 11.5px;
  b { display: block; margin-bottom: 4px; font-size: 12px; }
  .sa-row { display: flex; gap: 6px; align-items: center; padding: 2px 0; }
  .lv { font-size: 9.5px; font-weight: 700; border-radius: 3px; padding: 0 4px;
    &.fatal { background: rgba(246,70,93,.18); color: #F6465D; }
    &.warn { background: rgba(240,185,11,.15); color: #F0B90B; }
    &.info { background: rgba(74,156,255,.15); color: #4A9CFF; } }
  .sa-at { color: var(--el-text-color-placeholder); }
  .sa-txt { flex: 1; color: var(--el-text-color-regular); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sa-empty { color: var(--el-text-color-placeholder); } }
</style>
