<template>
  <div class="mixdash">
    <!-- 跑马灯（WS marquee 频道，dcm 全服务广播） -->
    <div v-if="marqueeText" class="marquee">
      <span class="dot" :class="{on: wsOn}"></span>📢 {{ marqueeText }}
    </div>

    <!-- 全局工作流管道（8 段·分策略六色堆叠，/monitor/overview 真信号） -->
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

    <div class="cols">
      <div class="left">
        <!-- 顶部：策略过滤 + 排序 -->
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

        <!-- 坑位行（币种行兼列头 + ↳账户子行 + 右键菜单） -->
        <VirtualPositionTable
          :rows="rows" :sort-key="sortKey" :sort-dir="sortDir" :height="tableH"
          @action="onAction" @rule-override="onRuleOverride" />

        <div class="foot">
          在管 {{ totalCount }} · 当日收益
          <b :class="(ov.pnl_today||0) >= 0 ? 'up' : 'down'">{{ fmtPnl(ov.pnl_today) }}</b> USDT ·
          phase 枚举 {{ enumCount }} 态 ·
          WS <span class="dot" :class="{on: wsOn}"></span>{{ wsOn ? '已连接' : '重连中…' }}
        </div>
      </div>

      <!-- 右栏（画板：系统健康/风控护栏/告警时间线/支撑域A/支撑域B，全真信号只读） -->
      <div class="rail">
        <div class="card">
          <div class="chd">系统健康 <b class="up">{{ ov.health?.ok ?? '—' }}/{{ ov.health?.total ?? '—' }}</b></div>
          <div class="svc-grid">
            <span v-for="(st, name) in ov.health?.services || {}" :key="name" class="svc"
                  :title="name + ': ' + st">
              <i class="dot2" :class="{bad: st !== 'ok'}"></i>{{ name }}
            </span>
          </div>
        </div>

        <div class="card">
          <div class="chd">风控护栏</div>
          <div class="kv"><span>实盘总权益</span><b>{{ num(ov.risk?.total_equity) }} U</b></div>
          <div class="kv"><span>净敞口越线</span><b :class="ov.risk?.net_breaches ? 'down' : 'up'">{{ ov.risk?.net_breaches ?? '—' }}（地板 {{ ov.risk?.net_floor ?? '—' }}U）</b></div>
          <div class="kv"><span>孤儿实盘仓</span><b :class="ov.risk?.orphans ? 'down' : 'up'">{{ ov.risk?.orphans ?? '—' }}</b></div>
          <div class="kv"><span>最高有效杠杆</span><b>{{ ov.risk?.max_lev ?? '—' }}x</b></div>
          <div class="kv"><span>本轮告警</span><b :class="ov.risk?.alerts_this_round ? 'warn' : 'up'">{{ ov.risk?.alerts_this_round ?? '—' }}</b></div>
        </div>

        <div class="card">
          <div class="chd">告警时间线</div>
          <div v-for="(a, i) in alerts.slice(0, 8)" :key="i" class="alert-row">
            <span class="lv" :class="a.level.toLowerCase()">{{ a.level }}</span>
            <span v-if="a.strategy" class="sbadge" :style="{background: SC[a.strategy]}">{{ a.strategy }}</span>
            <span class="atxt" :title="a.text">{{ a.text }}</span>
          </div>
          <div v-if="!alerts.length" class="empty">暂无告警</div>
        </div>

        <div class="card">
          <div class="chd">支撑域 A · AI 决策 <span class="ro">只读</span></div>
          <div v-for="ad in ov.advisors || []" :key="ad.name" class="kv">
            <span :title="ad.cadence">{{ ad.name }}</span>
            <b :class="ad.status.includes('停更') ? 'down' : 'up'">{{ ad.status }}</b>
          </div>
          <div class="fnote">摘除=只持有不新增、只告警不动手（治理在 dcm 控制台）</div>
        </div>

        <div class="card">
          <div class="chd">支撑域 B · 风控与运营
            <b :class="supportOk === (ov.support_b||[]).length ? 'up' : 'warn'">{{ supportOk }}/{{ (ov.support_b||[]).length }}</b>
          </div>
          <div class="sup-grid">
            <span v-for="g in ov.support_b || []" :key="g.name" class="svc">
              <i class="dot2" :class="{bad: !g.ok}"></i>{{ g.name }}
            </span>
          </div>
        </div>
      </div>
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
const alerts = ref([])
const filterStrategy = ref('')
const sortKey = ref('opened_at')
const sortDir = ref('asc')
const loading = ref(false)
const tableH = Math.max(420, window.innerHeight - 360)

const totalCount = computed(() => rows.value.reduce((n, r) => n + (r.positionCount || 0), 0))
const enumCount = computed(() => (enums.value.PhaseCode || []).length)
const supportOk = computed(() => (ov.value.support_b || []).filter(g => g.ok).length)

const num = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))
const fmtPnl = v => (v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2))

async function load() {
  loading.value = true
  try {
    rows.value = await mixApi.positions({ sort: sortKey.value, dir: sortDir.value, strategy: filterStrategy.value })
  } catch (e) {
    ElMessage.error(e?.error || '加载失败')
  } finally { loading.value = false }
}
async function loadRail() {
  try {
    ov.value = await mixApi.monitor.overview()
    alerts.value = await mixApi.alerts()
  } catch (e) { /* 右栏降级不阻断主表 */ }
}
function setStrategy(code) { filterStrategy.value = code; load() }
function flipDir() { sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'; load() }

/** 右键菜单/行内钮动作：confirm 项先弹确认浮层；409=状态机拒绝原样回显 */
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

// WS：跑马灯 + position:updates 实时对账
const marqueeText = ref('')
const wsOn = ref(false)
let wsDisconnect = null
let railTimer = null

onMounted(async () => {
  enums.value = await mixApi.enums()
  strategies.value = await mixApi.strategies()
  await load()
  loadRail()
  railTimer = setInterval(loadRail, 15000)
  wsDisconnect = connectStream((msg) => {
    wsOn.value = true
    if (msg.channel === 'marquee') {
      const d = msg.data || {}
      marqueeText.value = d.text || d.title || d.content || JSON.stringify(d).slice(0, 160)
    } else if (msg.channel === 'position:updates') {
      load()
    }
  })
})
onUnmounted(() => { wsDisconnect && wsDisconnect(); wsOn.value = false; railTimer && clearInterval(railTimer) })
</script>

<style scoped lang="scss">
.mixdash { display: flex; flex-direction: column; gap: 10px; }

/* 全局管道 */
.pipeline { display: flex; gap: 8px; align-items: stretch; overflow-x: auto; padding: 2px 0; }
.pseg { position: relative; flex: 1; min-width: 108px; background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  border-radius: 8px; padding: 8px 12px 10px; color: var(--mix-t1, #EAECEF); }
.pnum { font-size: 20px; font-weight: 800; line-height: 1.1; }
.plabel { font-size: 11px; color: var(--mix-t2, #848E9C); margin: 2px 0 6px; }
.pnote { margin-left: 6px; color: var(--mix-accent, #F0B90B); }
.pstack { display: flex; height: 4px; border-radius: 2px; overflow: hidden; background: var(--mix-border, #262B33); }
.pchunk { display: block; height: 100%; }
.parrow { position: absolute; right: -9px; top: 40%; color: var(--mix-t3, #5E6673); z-index: 1; }

/* 两栏 */
.cols { display: flex; gap: 10px; align-items: flex-start; }
.left { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.rail { width: 302px; flex: none; display: flex; flex-direction: column; gap: 10px; }
@media (max-width: 1280px) { .cols { flex-direction: column; } .rail { width: 100%; } }

.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; }
.chd { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.ro { font-size: 10px; color: var(--mix-t3, #5E6673); border: 1px solid var(--mix-border, #262B33); border-radius: 4px; padding: 0 5px; }
.svc-grid, .sup-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 3px 8px; }
.svc { font-size: 10.5px; color: var(--mix-t2, #848E9C); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dot2 { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--mix-green, #0ECB81); margin-right: 5px;
  &.bad { background: var(--mix-red, #F6465D); } }
.kv { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--mix-t2, #848E9C); padding: 2px 0;
  b { color: var(--mix-t1, #EAECEF); font-weight: 600; } }
.alert-row { display: flex; align-items: center; gap: 6px; font-size: 11px; padding: 3px 0; }
.lv { font-size: 9.5px; font-weight: 700; border-radius: 3px; padding: 0 4px;
  &.fatal { background: rgba(246,70,93,.18); color: var(--mix-red, #F6465D); }
  &.warn { background: rgba(240,185,11,.15); color: var(--mix-accent, #F0B90B); }
  &.info { background: rgba(74,156,255,.15); color: var(--mix-blue, #4A9CFF); } }
.sbadge { font-size: 9.5px; font-weight: 800; color: #0B0E11; border-radius: 3px; padding: 0 4px; }
.atxt { flex: 1; color: var(--mix-t2, #848E9C); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.empty { font-size: 11px; color: var(--mix-t3, #5E6673); }
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
.marquee { padding: 6px 12px; border-radius: 6px; font-size: 12px; background: rgba(240,185,11,.08);
  border: 1px solid rgba(240,185,11,.35); color: #F0B90B; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--el-border-color); margin-right: 6px;
  &.on { background: #2DD4BF; } }
</style>
