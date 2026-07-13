<template>
  <div class="mixdash">
    <!-- 跑马灯已全局化(Layout 顶栏);本页 WS 仅消费 position:updates -->
    <!-- 全局工作流管道（8 段·分策略六色堆叠·活跃段流光动效） -->
    <div class="pipeline" v-if="ov.pipeline?.length">
      <div v-for="(seg, i) in ov.pipeline" :key="seg.label" class="pseg" :class="{ live: seg.total > 0 }">
        <div class="pnum">{{ seg.total }}</div>
        <div class="plabel">{{ seg.label }}<span v-if="seg.note" class="pnote">{{ seg.note }}</span></div>
        <div class="pstack" :class="{ live: seg.total > 0 }">
          <span v-for="(n, code) in seg.split" :key="code" class="pchunk"
                :style="{flex: n, background: SC[code] || '#5E6673'}" :title="`${code}: ${n}`"></span>
        </div>
        <span v-if="i < ov.pipeline.length - 1" class="parrow" :class="{ flow: seg.total > 0 }">›</span>
      </div>
    </div>

    <!-- 真实决策事件流（引擎决策流水/路由变更/结算入账/上市,20s 轮询;悬停暂停） -->
    <div class="dfeed" v-if="feedLoop.length">
      <span class="dlbl">决策流</span>
      <div class="dtrack">
        <div class="dinner" :style="{ animationDuration: feedDur }">
          <span v-for="(f, idx) in feedLoop" :key="idx" class="ditem">
            <i class="dbadge" :style="{ background: SC[f.code] || '#5E6673' }">{{ f.code }}</i>
            <em class="dkind">{{ f.kind }}</em>{{ f.text }}<b class="dts">{{ shortTs(f.ts) }}</b>
          </span>
        </div>
      </div>
    </div>

    <!-- 过滤 + 排序 -->
    <div class="bar">
      <div class="chips">
        <span class="chip" :class="{on:!filterStrategy}" @click="setStrategy('')">全部 {{ totalCount }}</span>
        <span v-for="s in strategies" :key="s.code" class="chip"
              :class="{on:filterStrategy===s.code}"
              :style="filterStrategy===s.code
                ? {background:META[s.code].color,color:'#0B0E11',borderColor:META[s.code].color}
                : {background:META[s.code].colorBg,color:META[s.code].color,borderColor:META[s.code].color+'66'}"
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
      @action="onAction" @rule-template="onRuleTemplate" @rule-symbol="onRuleSymbol" />

    <!-- 通用规则(策略级) / 单一规则(某币) / 划转 弹层 -->
    <RuleSettingsModal v-model="ruleModal.open" :code="ruleModal.code" />
    <SymbolRuleModal v-model="symModal.open" :symbol="symModal.symbol" :code="symModal.code" />
    <TransferModal v-model="transferModal.open" :accounts="transferModal.accounts" :default-sub="transferModal.sub" />

    <!-- 底部横排三卡：策略总览缩略 / 账户余额水位预警 / 分策略管道总览 -->
    <div class="botrow">
      <div class="card">
        <div class="chd">策略总览
          <span class="hd-stat">在管 <b>{{ totalCount }}</b> · 当日收益 <b :class="(ov.pnl_today||0) >= 0 ? 'up' : 'down'">{{ fmtPnl(ov.pnl_today) }}</b> U</span>
          <el-link type="warning" @click="$router.push('/mix/strategies')">全页 →</el-link>
        </div>
        <div v-for="s in strategies" :key="s.code" class="srow">
          <span class="sbadge" :style="{background: SC[s.code]}" @click="$router.push('/mix/strategy/'+s.code)">{{ s.code }}</span>
          <span class="snm" @click="$router.push('/mix/strategy/'+s.code)">{{ s.name }}</span>
          <span class="skpi sl">{{ s.slots }} 仓</span>
          <span class="skpi">{{ (s.notional||0).toLocaleString() }}U</span>
          <b class="skpi pf" :class="(s.pnlTotal||0) >= 0 ? 'up' : 'down'">{{ (s.pnlTotal||0).toFixed(2) }}</b>
          <!-- 模式：紧凑标签,S2 可点切换(armed 需 ARM 确认);其余只读 -->
          <i class="mtag" :class="[s.mode, {clickable: s.modeSwitchable}]"
             :title="s.modeSwitchable ? '点击切换 影子/武装' : '引擎 env 控制,不可网页热切'"
             @click.stop="s.modeSwitchable && switchMode(s, s.mode==='armed' ? 'shadow' : 'armed')">{{ modeLabel(s.mode) }}</i>
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
        <div class="chd">分策略管道总览
          <!-- 真系统健康监控（原 footer 硬编码文字改为实时状态） -->
          <span class="hd-health" @click="$router.push('/system')">
            <i class="hdot" :class="{bad: healthBad}"></i>
            服务 {{ ov.health?.ok ?? '—' }}/{{ ov.health?.total ?? '—' }} ·
            护栏 <b :class="ov.risk?.alerts_this_round ? 'warn' : 'up'">{{ ov.risk?.alerts_this_round ?? 0 }} 告警</b> ·
            WS <span class="hdot" :class="{bad: !wsOn}"></span>{{ wsOn ? '已连' : '重连中' }}
          </span>
        </div>
        <div v-for="s in strategies" :key="s.code" class="prow">
          <span class="sbadge" :style="{background: SC[s.code]}">{{ s.code }}</span>
          <span class="pipe-mini">
            <i v-for="(v, k) in s.pipeline" :key="k"><em>{{ k }}</em><b>{{ v }}</b></i>
          </span>
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
import RuleSettingsModal from '../../components/rules/RuleSettingsModal.vue'
import SymbolRuleModal from '../../components/rules/SymbolRuleModal.vue'
import TransferModal from '../../components/rules/TransferModal.vue'
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
const healthBad = computed(() => { const h = ov.value.health; return h ? (h.ok < h.total) : false })
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
// 决策事件流(管道条下滚动;后端聚合三引擎流水/路由变更/结算入账,全真)
const feed = ref([])
const feedLoop = computed(() => (feed.value.length ? [...feed.value, ...feed.value] : []))
const feedDur = computed(() => `${Math.max(30, feed.value.length * 7)}s`)
const shortTs = (t) => {
  const d = new Date(t)
  return isNaN(d) ? '' : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
async function loadFeed() { try { feed.value = await mixApi.monitor.decisionFeed() } catch (e) { /* 降级 */ } }
// 秒级高频轮询：水位 + 当日收益 + 系统健康（后端读缓存快照,轻量）
async function loadWater() {
  try {
    const [wm, o] = await Promise.all([mixApi.monitor.watermarks(), mixApi.monitor.overview()])
    watermarks.value = wm; ov.value = o
  } catch (e) { /* 降级 */ }
}
function setStrategy(code) { filterStrategy.value = code; load() }
function flipDir() { sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'; load() }

// S3(coin) 菜单动作走 coin 菜单代理端点（桥→coin 状态机权威）
const S3_MENU_KEYS = ['push_symbol', 'remove_slot', 'resume_slot', 'manual_open', 'blacklist',
  'force_close', 'manual_hedge', 'manual_repay', 'partial_repay', 'batch_remove', 'max_borrowable', 'transfer']
async function onAction({ action, rowId, accountId }) {
  const row = rows.value.find(r => r.id === rowId)
  const item = row ? (CONTEXT_MENUS[row.strategyCode] || []).find(i => i.key === action) : null
  try {
    if (item?.confirm) {
      await ElMessageBox.confirm(`确认对 ${row.symbol}${accountId ? ' · ' + accountId : ''} 执行「${item.label}」？`, '危险操作', { type: 'warning', confirmButtonText: '执行' })
    }
    // S3 走 coin 菜单代理（真实操作,coin 50U保护/还币闸/状态机原样生效）
    if (row?.strategyCode === 'S3' && S3_MENU_KEYS.includes(action)) {
      // 划转=弹窗（内部/跨账户,coin 契约 from_wallet/to_wallet）
      if (action === 'transfer') { await openTransferModal(accountId); return }
      const extra = {}
      if (action === 'manual_open') {
        const { value } = await ElMessageBox.prompt('手动开仓金额（USDT,留空=按规则 order_amount）', `手动开仓 · ${row.symbol}`, { inputValue: '10' })
        if (value !== '' && value != null) extra.amount = parseFloat(value)
      }
      if (action === 'partial_repay') {
        const { value } = await ElMessageBox.prompt(
          '还币金额（USDT,coin 按现价换算币数量；后缀 p=还后暂停自动借币30分钟,如 20p）',
          `部分还币 · ${row.symbol}`, { inputValue: '' })
        const s = String(value || '').trim()
        if (!s) { ElMessage.info('未输入金额,已取消'); return }
        if (s.toLowerCase().endsWith('p')) { extra.pause_borrow = true; extra.amount_usdt = parseFloat(s.slice(0, -1)) }
        else extra.amount_usdt = parseFloat(s)
        if (!extra.amount_usdt || extra.amount_usdt <= 0) { ElMessage.error('金额非法'); return }
      }
      const r = await mixApi.coinMenu(row.symbol, { action, sub: accountId, ...extra })
      if (action === 'max_borrowable') {
        const c = r?.coin || {}
        ElMessageBox.alert(
          `${c.asset || row.symbol}：最大可借 ${c.max_borrowable ?? '—'}（借币限额 ${c.borrow_limit ?? '—'}）`,
          `刷新可借 · ${accountId || ''}`, { confirmButtonText: '知道了' })
        return
      }
      ElMessage.success(`已受理：${item?.label || action}（coin 状态机执行）`)
      setTimeout(load, 900); return
    }
    const r = await mixApi.positionAction(rowId, action, accountId, `${action}:${rowId}:${Date.now()}`)
    ElMessage.success(r?.note || '已受理（202），结果以 WS 对账')
    setTimeout(load, 900)
  } catch (e) {
    if (e === 'cancel') return
    ElMessage.error(e?.error || e?.detail || '被拒绝')
  }
}
const ruleModal = ref({ open: false, code: 'S3' })
const symModal = ref({ open: false, symbol: '', code: 'S3' })
function onRuleTemplate({ code }) { ruleModal.value = { open: true, code } }
function onRuleSymbol({ symbol, code }) { symModal.value = { open: true, symbol, code } }

// 划转弹窗（账户清单=coin 面板子账户,实时余额随行）
const transferModal = ref({ open: false, sub: null, accounts: [] })
async function openTransferModal(accountId) {
  try {
    const f = await mixApi.fundRulesS3()
    transferModal.value = {
      open: true,
      accounts: (f.accounts || []).map(a => ({ sub: a.sub, note: a.note, balance: a.balance })),
      sub: (f.accounts || []).find(a => a.note === accountId || String(a.sub) === String(accountId))?.sub ?? null,
    }
  } catch (e) { ElMessage.error(e?.detail || e?.error || '账户清单读取失败') }
}

const modeLabel = m => ({ shadow: '影子', armed: '武装', 未启用: '未启用' }[m] || m || '—')
async function switchMode(s, mode) {
  try {
    let confirm
    if (mode === 'armed') {
      const { value } = await ElMessageBox.prompt(`切换 ${s.code} 为「武装」= 真金下单。输入 ARM 确认（风控联锁）`, '武装确认', { inputPattern: /^ARM$/, inputErrorMessage: '必须输入 ARM' })
      confirm = value
    } else {
      await ElMessageBox.confirm(`切换 ${s.code} 为「影子」（停真金下单）？`, '模式切换', { type: 'warning' })
    }
    await mixApi.strategyMode(s.code, mode, confirm)
    ElMessage.success(`${s.code} 已切 ${modeLabel(mode)}`)
    loadAux()
  } catch (e) { if (e !== 'cancel') { ElMessage.error(e?.detail || e?.error || '切换失败'); loadAux() } }
}

let wsDisconnect = null
let auxTimer = null
let waterTimer = null
let feedTimer = null

onMounted(async () => {
  enums.value = await mixApi.enums()
  await load()
  loadAux()
  loadFeed()
  auxTimer = setInterval(loadAux, 15000)
  waterTimer = setInterval(loadWater, 3000)   // 水位秒级(后端读8s快照,前端3s取最新)
  feedTimer = setInterval(loadFeed, 20000)    // 决策流20s(shadow流水分钟级,再快无新事件)
  // 坑位表毫秒级：直接用 Rust WS hub 中继的全量行换表（不再走 REST 回环）
  wsDisconnect = connectStream((msg) => {
    if (msg.channel !== 'position:updates') return
    if (Array.isArray(msg.rows) && msg.rows.length && typeof msg.rows[0] === 'object' && msg.rows[0].symbol) {
      // 帧内是全量行：按当前策略过滤+排序客户端应用（毫秒级,无网络往返）
      let rs = msg.rows
      if (filterStrategy.value) rs = rs.filter(r => r.strategyCode === filterStrategy.value)
      rs = [...rs].sort((a, b) => {
        const d = sortDir.value === 'asc' ? 1 : -1
        if (sortKey.value === 'pnl') return ((a.pnl ?? -Infinity) - (b.pnl ?? -Infinity)) * d
        return (String(a.openedAt || '') > String(b.openedAt || '') ? 1 : -1) * d
      })
      rows.value = rs
    } else {
      load()  // 老式摘要帧兜底
    }
  })
})
onUnmounted(() => { wsDisconnect && wsDisconnect(); auxTimer && clearInterval(auxTimer); waterTimer && clearInterval(waterTimer); feedTimer && clearInterval(feedTimer) })
</script>

<style scoped lang="scss">
/* 满高布局: 坑位表 flex 填余量,主控台整页不出浏览器滚动条(窗口过矮时回落到 .page 内滚动)
   注意:固定行必须 flex:none,否则被 flex 压缩产生遮挡(管道条被剪的回归课) */
.mixdash { display: flex; flex-direction: column; gap: 10px; height: 100%;
  > .pipeline, > .dfeed, > .bar, > .botrow, > .foot { flex: none; } }

.pipeline { display: flex; gap: 8px; align-items: stretch; overflow-x: auto; padding: 2px 0; }
.pseg { position: relative; flex: 1; min-width: 104px; background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33);
  border-radius: 8px; padding: 8px 12px 10px; color: var(--mix-t1, #EAECEF); }
.pnum { font-size: 20px; font-weight: 800; line-height: 1.1; }
.plabel { font-size: 11px; color: var(--mix-t2, #848E9C); margin: 2px 0 6px; }
.pnote { margin-left: 6px; color: var(--mix-accent, #F0B90B); }
.pstack { display: flex; height: 4px; border-radius: 2px; overflow: hidden; background: var(--mix-border, #262B33); position: relative; }
.pchunk { display: block; height: 100%; }
.parrow { position: absolute; right: -9px; top: 40%; color: var(--mix-t3, #5E6673); z-index: 1; }

/* 工作流动效:活跃段(total>0)堆叠条流光扫过 + 段间箭头金色脉冲;静止段不装忙 */
.pseg.live { border-color: rgba(240, 185, 11, .22); }
.pstack.live::after { content: ''; position: absolute; inset: 0; border-radius: 2px; pointer-events: none;
  background: linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, .38) 50%, transparent 100%);
  background-size: 200% 100%; animation: pflow 2.8s linear infinite; }
@keyframes pflow { from { background-position: 200% 0; } to { background-position: -200% 0; } }
.parrow.flow { color: var(--mix-accent, #F0B90B); animation: parrowpulse 1.6s ease-in-out infinite; }
@keyframes parrowpulse { 0%, 100% { opacity: .35; transform: translateX(0); } 50% { opacity: 1; transform: translateX(2px); } }

/* 决策事件流(横向滚动;悬停暂停;两份内容 -50% 无缝循环) */
.dfeed { display: flex; align-items: center; gap: 8px; background: var(--mix-card, #181B21);
  border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 4px 10px; overflow: hidden; }
.dlbl { flex: none; font-size: 10.5px; font-weight: 800; color: var(--mix-accent, #F0B90B); letter-spacing: 1px; }
.dtrack { flex: 1; overflow: hidden; }
.dinner { display: inline-flex; gap: 26px; padding-right: 26px; white-space: nowrap;
  animation: dscroll linear infinite; will-change: transform;
  &:hover { animation-play-state: paused; } }
@keyframes dscroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.ditem { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--mix-t2, #848E9C); }
.dbadge { font-style: normal; font-size: 9px; font-weight: 800; color: #0B0E11; border-radius: 3px; padding: 0 4px; }
.dkind { font-style: normal; color: var(--mix-t1, #EAECEF); font-weight: 600; }
.dts { font-weight: 500; color: var(--mix-t3, #5E6673); margin-left: 2px; }

.botrow { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; }
.chd { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.hd-stat { margin-left: auto; margin-right: 8px; font-size: 11px; font-weight: 500; color: var(--mix-t2, #848E9C);
  b { font-weight: 700; color: var(--mix-t1, #EAECEF); &.up { color: #0ECB81; } &.down { color: #F6465D; } } }
.hd-health { margin-left: auto; font-size: 10.5px; font-weight: 500; color: var(--mix-t2, #848E9C); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;
  b { font-weight: 700; &.up { color: #0ECB81; } &.warn { color: #F0B90B; } }
  &:hover { color: var(--mix-t1, #EAECEF); } }
.hdot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #0ECB81; &.bad { background: #F6465D; } }
.srow { display: flex; align-items: center; gap: 8px; font-size: 11.5px; padding: 3px 0; color: var(--mix-t2, #848E9C);
  &:hover { color: var(--mix-t1, #EAECEF); } }
.snm { flex: 1; min-width: 60px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
.mtag { flex: none; width: 44px; text-align: center; font-style: normal; font-size: 9.5px; padding: 2px 0; border-radius: 4px; font-weight: 700;
  background: rgba(94,102,115,.15); color: var(--mix-t3, #5E6673);
  &.armed { background: rgba(246,70,93,.15); color: #F6465D; }
  &.shadow { background: rgba(74,156,255,.15); color: #4A9CFF; }
  &.clickable { cursor: pointer; &:hover { filter: brightness(1.3); } } }
.skpi { flex: none; text-align: right; font-variant-numeric: tabular-nums;
  &.sl { width: 44px; } width: 58px; &.pf { width: 62px; font-weight: 700; } }
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
