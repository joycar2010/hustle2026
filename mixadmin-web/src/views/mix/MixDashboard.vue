<template>
  <div class="mixdash">
    <!-- 跑马灯已全局化(Layout 顶栏);本页 WS 仅消费 position:updates -->
    <!-- 全局工作流管道（8 段·分策略六色堆叠） -->
    <div class="pipeline" v-if="ov.pipeline?.length">
      <div v-for="(seg, i) in ov.pipeline" :key="seg.label" class="pseg">
        <div class="pnum">{{ seg.total }}</div>
        <div class="plabel">{{ seg.label }}<span v-if="seg.note" class="pnote">{{ seg.note }}</span></div>
        <div class="pstack">
          <span v-for="(n, code) in seg.split" :key="code" class="pchunk"
                :style="{flex: n, background: SC[code] || '#5E6673'}" :title="`${code}: ${n}`"></span>
        </div>
        <span v-if="i < ov.pipeline.length - 1" class="parrow">›</span>
      </div>
    </div>

    <!-- 过滤 + 排序 -->
    <div class="bar">
      <div class="chips">
        <span class="chip" :class="{on:!filterStrategy}" @click="setStrategy('')">全部 {{ totalCount }}</span>
        <span v-for="s in strategies" :key="s.code" class="chip"
              :class="{on:filterStrategy===s.code}"
              :style="filterStrategy===s.code?{background:META[s.code].colorBg,color:META[s.code].color,borderColor:META[s.code].color}:{}"
              @click="setStrategy(s.code)">
          {{ s.code }}·{{ s.name }}
        </span>
      </div>
      <div class="right">
        <el-radio-group v-model="sortKey" size="small" @change="load">
          <el-radio-button value="opened_at">发起时间</el-radio-button>
          <el-radio-button value="pnl">收益</el-radio-button>
        </el-radio-group>
        <el-button size="small" @click="flipDir">{{ sortDir==='asc'?'早→晚 / 低→高':'晚→早 / 高→低' }}</el-button>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 坑位行（全宽,自适应填满剩余高度=页面级无滚动条） -->
    <VirtualPositionTable
      :rows="rows" :sort-key="sortKey" :sort-dir="sortDir" :height="0"
      @action="onAction" @rule-override="onRuleOverride" />

    <!-- 底部横排三卡：策略总览缩略 / 账户余额水位预警 / 分策略管道总览 -->
    <div class="botrow">
      <div class="card">
        <div class="chd">策略总览 <el-link type="warning" @click="$router.push('/mix/strategies')">全页 →</el-link></div>
        <div v-for="s in strategies" :key="s.code" class="srow" @click="$router.push('/mix/strategy/'+s.code)">
          <span class="sbadge" :style="{background: SC[s.code]}">{{ s.code }}</span>
          <span class="snm">{{ s.name }}</span>
          <span class="skpi">{{ s.slots }} 仓</span>
          <span class="skpi">{{ (s.notional||0).toLocaleString() }}U</span>
          <b class="skpi" :class="(s.pnlTotal||0) >= 0 ? 'up' : 'down'">{{ (s.pnlTotal||0).toFixed(2) }}</b>
          <i class="sdot2" :class="{off: !s.enabled}"></i>
        </div>
      </div>

      <div class="card">
        <div class="chd">账户余额水位预警 <b :class="warnCount ? 'warn' : 'up'">{{ warnCount }} 预警</b></div>
        <div v-for="w in watermarks" :key="w.account" class="wrow">
          <span class="wnm">{{ w.account }}</span>
          <span class="wamt">{{ w.available }}</span>
          <span class="wbar"><i :style="{width: (w.level*100)+'%', background: wcolor(w)}" /></span>
          <span class="wth" :style="{color: wcolor(w)}">{{ wlabel(w) }}</span>
        </div>
        <div class="fnote">水位=权益/目标（fund-scheduler 提案制，人工划转执行）</div>
      </div>

      <div class="card">
        <div class="chd">分策略管道总览</div>
        <div v-for="s in strategies" :key="s.code" class="prow">
          <span class="sbadge" :style="{background: SC[s.code]}">{{ s.code }}</span>
          <span class="pipe-mini">
            <i v-for="(v, k) in s.pipeline" :key="k"><em>{{ k }}</em><b>{{ v }}</b></i>
          </span>
        </div>
      </div>
    </div>

    <div class="foot">
      在管 {{ totalCount }} · 当日收益
      <b :class="(ov.pnl_today||0) >= 0 ? 'up' : 'down'">{{ fmtPnl(ov.pnl_today) }}</b> USDT ·
      系统健康与风控护栏 → 屏3·风控墙 ·
      WS <span class="dot" :class="{on: wsOn}"></span>{{ wsOn ? '已连接' : '重连中…' }}
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { connectStream } from '../../api/mixWs'
import { ElMessage, ElMessageBox } from 'element-plus'
import VirtualPositionTable from '../../components/PositionTable/VirtualPositionTable.vue'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { CONTEXT_MENUS } from '../../components/PositionTable/strategyColumns'
import { mixApi } from '../../api/mix'

const SC = { S1: '#4A9CFF', S2: '#F0B90B', S3: '#A78BFA', S4: '#2DD4BF', S5: '#FF9F43', S6: '#F472B6' }

const rows = ref([])
const strategies = ref([])
const enums = ref({})
const ov = ref({})
const watermarks = ref([])
const filterStrategy = ref('')
const sortKey = ref('opened_at')
const sortDir = ref('asc')
const loading = ref(false)

const totalCount = computed(() => rows.value.reduce((n, r) => n + (r.positionCount || 0), 0))
const warnCount = computed(() => watermarks.value.filter(w => w.threshold !== 'ok').length)
const fmtPnl = v => (v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2))
const wcolor = w => w.threshold === 'withdraw' ? '#F6465D' : w.threshold === 'topup' ? '#F0B90B' : '#0ECB81'
const wlabel = w => w.threshold === 'ok' ? '正常'
  : `${{ topup: '补仓线', withdraw: '提现线' }[w.threshold] || ''}·需补 ${Math.ceil(w.deficit_usdt || 0)}U`

async function load() {
  loading.value = true
  try {
    rows.value = await mixApi.positions({ sort: sortKey.value, dir: sortDir.value, strategy: filterStrategy.value })
  } catch (e) {
    ElMessage.error(e?.error || '加载失败')
  } finally { loading.value = false }
}
async function loadAux() {
  try {
    ov.value = await mixApi.monitor.overview()
    strategies.value = await mixApi.strategies()
    watermarks.value = await mixApi.monitor.watermarks()
  } catch (e) { /* 辅助区降级不阻断主表 */ }
}
function setStrategy(code) { filterStrategy.value = code; load() }
function flipDir() { sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'; load() }

async function onAction({ action, rowId, accountId }) {
  const row = rows.value.find(r => r.id === rowId)
  const item = row ? (CONTEXT_MENUS[row.strategyCode] || []).find(i => i.key === action) : null
  try {
    if (item?.confirm) {
      await ElMessageBox.confirm(`确认对 ${row.symbol}${accountId ? ' · ' + accountId : ''} 执行「${item.label}」？`, '危险操作', { type: 'warning', confirmButtonText: '执行' })
    }
    const r = await mixApi.positionAction(rowId, action, accountId, `${action}:${rowId}:${Date.now()}`)
    ElMessage.success(r?.note || '已受理（202），结果以 WS 对账')
    setTimeout(load, 900)
  } catch (e) {
    if (e === 'cancel') return
    ElMessage.error(e?.error || e?.detail || '被拒绝')
  }
}
function onRuleOverride(rowId) {
  const row = rows.value.find(r => r.id === rowId)
  ElMessageBox.alert(`打开规则中心 · 币种覆盖：${row?.symbol}（当前 ${row?.ruleScope === 'template' ? '通用规则' : '单独规则'}）`, '单独规则')
}

let wsDisconnect = null
let auxTimer = null

onMounted(async () => {
  enums.value = await mixApi.enums()
  await load()
  loadAux()
  auxTimer = setInterval(loadAux, 15000)
  wsDisconnect = connectStream((msg) => {
    if (msg.channel === 'position:updates') load()
  })
})
onUnmounted(() => { wsDisconnect && wsDisconnect(); auxTimer && clearInterval(auxTimer) })
</script>

<style scoped lang="scss">
/* 满高布局: 坑位表 flex 填余量,主控台整页不出浏览器滚动条(窗口过矮时回落到 .page 内滚动)
   注意:固定行必须 flex:none,否则被 flex 压缩产生遮挡(管道条被剪的回归课) */
.mixdash { display: flex; flex-direction: column; gap: 10px; height: 100%;
  > .pipeline, > .bar, > .botrow, > .foot { flex: none; } }

.pipeline { display: flex; gap: 8px; align-items: stretch; overflow-x: auto; padding: 2px 0; }
.pseg { position: relative; flex: 1; min-width: 104px; background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  border-radius: 8px; padding: 8px 12px 10px; color: var(--mix-t1, #EAECEF); }
.pnum { font-size: 20px; font-weight: 800; line-height: 1.1; }
.plabel { font-size: 11px; color: var(--mix-t2, #848E9C); margin: 2px 0 6px; }
.pnote { margin-left: 6px; color: var(--mix-accent, #F0B90B); }
.pstack { display: flex; height: 4px; border-radius: 2px; overflow: hidden; background: var(--mix-border, #262B33); }
.pchunk { display: block; height: 100%; }
.parrow { position: absolute; right: -9px; top: 40%; color: var(--mix-t3, #5E6673); z-index: 1; }

.botrow { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; }
.chd { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.srow { display: flex; align-items: center; gap: 8px; font-size: 11.5px; padding: 3px 0; cursor: pointer; color: var(--mix-t2, #848E9C);
  &:hover { color: var(--mix-t1, #EAECEF); } }
.snm { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.skpi { min-width: 52px; text-align: right; }
.sbadge { min-width: 24px; text-align: center; font-size: 9.5px; font-weight: 800; color: #0B0E11; border-radius: 3px; padding: 1px 4px; }
.sdot2 { width: 7px; height: 7px; border-radius: 50%; background: var(--mix-green, #0ECB81); &.off { background: var(--mix-t3, #5E6673); } }
.wrow { display: flex; align-items: center; gap: 8px; font-size: 11.5px; padding: 3px 0; color: var(--mix-t2, #848E9C); }
.wnm { min-width: 72px; font-weight: 600; color: var(--mix-t1, #EAECEF); }
.wamt { min-width: 60px; text-align: right; }
.wbar { flex: 1; height: 5px; background: var(--mix-border, #262B33); border-radius: 3px; overflow: hidden;
  i { display: block; height: 100%; border-radius: 3px; } }
.wth { min-width: 90px; text-align: right; font-weight: 700; font-size: 10.5px; }
.prow { display: flex; gap: 8px; align-items: baseline; padding: 3px 0; }
.pipe-mini { display: flex; gap: 8px; flex-wrap: wrap; font-size: 10.5px; color: var(--mix-t2, #848E9C);
  i { font-style: normal; em { font-style: normal; margin-right: 3px; } b { color: var(--mix-t1, #EAECEF); } } }
.fnote { font-size: 10px; color: var(--mix-t3, #5E6673); margin-top: 6px; }

.bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.chips { display: flex; gap: 6px; flex-wrap: wrap;
  .chip { padding: 3px 10px; border-radius: 6px; border: 1px solid var(--el-border-color); cursor: pointer; font-size: 12px; color: var(--el-text-color-secondary);
    &.on { background: #F0B90B; border-color: #F0B90B; color: #0B0E11; font-weight: 700; } } }
.right { display: flex; gap: 8px; align-items: center; }
.foot { font-size: 11px; color: var(--el-text-color-secondary); }
.up { color: var(--mix-green, #0ECB81); }
.down { color: var(--mix-red, #F6465D); }
.warn { color: var(--mix-accent, #F0B90B); }
</style>
