<template>
  <div class="mixreport">
    <el-tabs v-model="rtab">
    <el-tab-pane label="NAV 总览" name="nav">
      <div class="navcards">
        <div class="nc"><span>Accounting NAV</span><b>{{ n(nav.nav?.accounting_nav_usdt) }} U</b><i>交易所+账本事实口径</i></div>
        <div class="nc"><span>Risk-adjusted NAV</span><b>{{ n(nav.nav?.risk_adjusted_nav_usdt) }} U</b><i>扣受限/冻结/退出折价</i></div>
        <div class="nc"><span>Available Equity</span><b class="hl">{{ n(nav.nav?.available_equity_usdt) }} U</b><i>可立即部署</i></div>
        <div class="nc"><span>Trapped Capital</span><b :class="{bad:(nav.nav?.trapped_usdt||0)>0}">{{ n(nav.nav?.trapped_usdt) }} U</b><i>受限venue折价</i></div>
      </div>
      <div class="hd" style="margin-top:12px"><b>NAV bridge 恒等式</b><span class="sub">Δ(Accounting NAV) − 外部流 =?= 类目和(V2 §9.2 验收)</span>
        <el-button size="small" @click="loadBridge" style="margin-left:auto">刷新</el-button></div>
      <div class="bridge">
        <div class="bcat" v-for="(v,k) in bridge.categories||{}" :key="k"><span>{{ k }}</span><b :class="v>=0?'up':'down'">{{ fmt(v) }}</b></div>
      </div>
      <div class="bsum">
        <span>类目和(component) <b>{{ fmt(bridge.component_sum) }}</b></span>
        <span>外部流(income TRANSFER) <b>{{ fmt(bridge.external_flow_income) }}</b></span>
        <span>ΔNAV <b>{{ bridge.delta_nav==null?'N/A(快照不足2点)':fmt(bridge.delta_nav) }}</b></span>
        <span>残差 <b :class="resCls">{{ bridge.residual==null?'N/A':fmt(bridge.residual) }}</b></span>
        <span class="um">UNMAPPED <b :class="bridge.unmapped_count?'bad':'ok'">{{ bridge.unmapped_count ?? '—' }}</b></span>
        <span class="verdict" :class="bridge.identity_ok?'ok':'warn'">{{ bridge.identity_ok ? '恒等式通过 ✓' : (bridge.unmapped_count?'UNMAPPED>0':'待建NAV基线') }}</span>
      </div>
      <div class="fnote">{{ bridge.note }}</div>
    </el-tab-pane>
    <el-tab-pane label="收益归因" name="attr">
    <div class="bar">
      <b>收益趋势</b>
      <el-radio-group v-model="chartType" size="small"><el-radio-button value="bar">柱形图</el-radio-button><el-radio-button value="line">累计净值(线)</el-radio-button></el-radio-group>
      <el-radio-group v-model="gran" size="small"><el-radio-button value="day">日</el-radio-button><el-radio-button value="week">周</el-radio-button><el-radio-button value="month">月</el-radio-button></el-radio-group>
      <el-radio-group v-model="range" size="small" @change="load">
        <el-radio-button value="30d">30天</el-radio-button><el-radio-button value="90d">90天</el-radio-button>
        <el-radio-button value="180d">半年</el-radio-button><el-radio-button value="all">全部</el-radio-button>
      </el-radio-group>
    </div>
    <div ref="chartEl" class="chart" />

    <div class="attr">
      <div class="hd"><b>收益归因（策略 × 科目）</b><span class="sub">逐回路记账 · 点行展开科目</span></div>
      <div class="band">
        <i v-for="a in attribution" :key="a.code" :style="{ width: (a.total/totalSum*100)+'%', background: META[a.code].color }" :title="`${a.code} ${a.name}`" />
      </div>
      <div v-for="a in attribution" :key="a.code" class="arow" @click="expanded = expanded===a.code ? '' : a.code">
        <span class="code" :style="{background:META[a.code].colorBg,color:META[a.code].color}">{{ a.code }}</span>
        <span class="nm">{{ a.name }}</span>
        <span class="track"><i :style="{ width: (a.total/maxTotal*100)+'%', background: META[a.code].color }" /></span>
        <b :class="a.total>=0?'up':'dn'">{{ a.total>=0?'+':'' }}{{ a.total.toLocaleString() }}</b>
        <span class="caret">{{ expanded===a.code ? '⌄' : '›' }}</span>
        <div v-if="expanded===a.code" class="subjects" @click.stop>
          <span v-for="(v,k) in a.subjects" :key="k" class="sj">
            <em>{{ subjectLabel(k) }}</em><b :class="v>=0?'up':'dn'">{{ v>=0?'+':'' }}{{ v.toLocaleString() }}</b>
          </span>
        </div>
      </div>
    </div>
    </el-tab-pane>
    <el-tab-pane label="资金流水" name="flow">
      <div class="hd"><b>提现资金流水</b><span class="sub">withdrawal_observation · 事实只读 · 无快捷提现按钮</span></div>
      <el-table :data="flows" size="small" stripe>
        <el-table-column prop="venue" label="Venue" width="90" />
        <el-table-column prop="asset" label="资产" width="80" />
        <el-table-column prop="amount" label="金额" width="120" align="right" />
        <el-table-column prop="status" label="状态" width="110"><template #default="{row}">
          <span :class="'fs-'+row.status">{{ row.status }}</span></template></el-table-column>
        <el-table-column prop="venue_tx_id" label="平台流水号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="chain_tx" label="链上tx" min-width="140" show-overflow-tooltip />
        <el-table-column prop="initiated_at" label="发起" width="150" />
      </el-table>
      <div class="fnote">入金/出金/内部划转/pending/failed/trapped/released 事实只读;门户与本页均不提供快捷提现或转账。</div>
    </el-tab-pane>
    <el-tab-pane label="Ledger · RECON" name="ledger">
      <div class="hd"><b>归一账本(income_records 投影)</b><span class="sub">源=append-only 真相;每条映射 NAV 类目;UNMAPPED 应为 0</span>
        <el-select v-model="lcat" size="small" style="width:150px;margin-left:auto" @change="loadLedger" clearable placeholder="全部类目">
          <el-option v-for="c in ['FEE','FUNDING','TRADING_PNL','BORROW','EARN','EXTERNAL_FLOW','SETTLEMENT','UNMAPPED']" :key="c" :value="c" /></el-select></div>
      <el-table :data="ledger" size="small" stripe max-height="320">
        <el-table-column prop="ts" label="时间" width="150" />
        <el-table-column prop="venue" label="Venue" width="80" />
        <el-table-column prop="symbol" label="标的" width="100" />
        <el-table-column prop="itype" label="账单类型" width="100" />
        <el-table-column label="NAV类目" width="130"><template #default="{row}">
          <span :class="row.nav_category==='UNMAPPED'?'bad':'dim'">{{ row.nav_category }}</span></template></el-table-column>
        <el-table-column prop="amount" label="金额" width="110" align="right"><template #default="{row}">
          <span :class="row.amount>=0?'up':'down'">{{ fmt(row.amount) }}</span></template></el-table-column>
        <el-table-column prop="strategy_code" label="策略" width="70" />
      </el-table>
      <div class="hd" style="margin-top:12px"><b>RECON 断点</b><b :class="{bad:recon.total}" style="margin-left:6px">{{ recon.total }}</b></div>
      <div v-if="!recon.breaks?.length" class="dimtxt pad">无断点(账本口径+持仓RECON 全清)</div>
      <div v-for="(b,i) in recon.breaks||[]" :key="i" class="brk">
        <span class="bk">{{ b.kind }}</span>{{ b.detail }}<span v-if="b.amount!=null" class="dimtxt"> · {{ fmt(b.amount) }}U</span></div>
      <div class="fnote">{{ recon.note }}</div>
    </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const chartEl = ref(null)
const chartType = ref('bar')
const gran = ref('day')
const range = ref('30d')
const rtab = ref('nav')
const nav = ref({}); const bridge = ref({}); const flows = ref([]); const ledger = ref([]); const recon = ref({}); const lcat = ref('')
const n = v => (v == null ? 'N/A' : Number(v).toLocaleString())
const fmt = v => (v == null ? 'N/A' : (v >= 0 ? '+' : '') + Number(v).toFixed(4))
const resCls = computed(() => { const r = bridge.value.residual; return r == null ? '' : Math.abs(r) < 1 ? 'ok' : 'bad' })
async function loadBridge(){ try{ bridge.value = await mixApi.navBridge(14) }catch(e){} }
async function loadNav(){ try{ nav.value = await mixApi.riskSummary() }catch(e){} }
async function loadFlows(){ try{ flows.value = (await mixApi.riskCashflows())?.rows || [] }catch(e){} }
async function loadLedger(){ try{ ledger.value = (await mixApi.ledgerEntries({days:30, category:lcat.value||undefined}))?.rows || [] }catch(e){} }
async function loadRecon(){ try{ recon.value = await mixApi.reconBreaks() }catch(e){} }
const daily = ref([])
const attribution = ref([])
const expanded = ref('')
let chart

const totalSum = computed(() => attribution.value.reduce((s, a) => s + a.total, 0) || 1)
const maxTotal = computed(() => Math.max(...attribution.value.map(a => a.total), 1))
const subjectLabel = k => ({ funding: '资金费', spread: '价差', fee: '手续费', interest: '利息', rebate: '返佣', spread_cost: '点差损耗' }[k] || k)

/** 周/月由前端对日粒度聚合（契约约定，不用后端三张表） */
function aggregate(rows, g) {
  if (g === 'day') return rows.map(r => ({ label: r.date.slice(5), net: r.net }))
  const bucket = new Map()
  for (const r of rows) {
    const d = new Date(r.date)
    const key = g === 'week' ? `${d.getFullYear()}-W${Math.ceil(((d - new Date(d.getFullYear(),0,1))/864e5 + 1)/7)}` : r.date.slice(0, 7)
    bucket.set(key, (bucket.get(key) || 0) + r.net)
  }
  return [...bucket].map(([label, net]) => ({ label, net }))
}

function render() {
  if (!chart) return
  const data = aggregate(daily.value, gran.value)
  if (chartType.value === 'bar') {
    chart.setOption({
      grid: { left: 50, right: 16, top: 24, bottom: 28 },
      xAxis: { type: 'category', data: data.map(d => d.label), axisLine: { lineStyle: { color: '#5E6673' } } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(94,102,115,.2)' } } },
      series: [{
        type: 'bar', data: data.map(d => ({
          value: d.net,
          itemStyle: { color: d.net >= 0 ? '#0ECB81' : '#F6465D', borderRadius: d.net >= 0 ? [3,3,0,0] : [0,0,3,3] },
          label: Math.abs(d.net) >= 400 ? { show: true, position: d.net >= 0 ? 'top' : 'bottom', fontSize: 9, color: d.net >= 0 ? '#0ECB81' : '#F6465D', formatter: v => Math.abs(v.value) >= 1000 ? (v.value/1000).toFixed(1)+'k' : v.value } : undefined,
        })),
      }],
      tooltip: { trigger: 'axis' },
    }, true)
  } else {
    let acc = 0
    const line = data.map(d => { acc += d.net; return acc })
    chart.setOption({
      grid: { left: 60, right: 16, top: 24, bottom: 28 },
      xAxis: { type: 'category', data: data.map(d => d.label), axisLine: { lineStyle: { color: '#5E6673' } } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(94,102,115,.2)' } } },
      series: [{ type: 'line', data: line, smooth: true, symbol: 'none',
        lineStyle: { color: '#FCD535', width: 2.5 },
        areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(240,185,11,.35)'},{offset:1,color:'rgba(240,185,11,0)'}]) } }],
      tooltip: { trigger: 'axis' },
    }, true)
  }
}

async function load() {
  ;[daily.value, attribution.value] = await Promise.all([mixApi.reportPnl(range.value), mixApi.attribution()])
  render()
}
watch([chartType, gran], render)
const onResize = () => chart?.resize()
onMounted(() => { chart = echarts.init(chartEl.value); window.addEventListener('resize', onResize); load(); loadNav(); loadBridge(); loadFlows(); loadLedger(); loadRecon() })
onUnmounted(() => { window.removeEventListener('resize', onResize); chart?.dispose() })
</script>

<style scoped lang="scss">
.mixreport { display: flex; flex-direction: column; gap: 12px; }
.bar { display: flex; gap: 12px; align-items: center; b { font-size: 14px; } }
.chart { height: 320px; border: 1px solid var(--el-border-color); border-radius: 10px; }
.attr { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 12px 14px; font-size: 12px;
  .hd { display: flex; gap: 8px; align-items: baseline; margin-bottom: 8px; b { font-size: 13px; } .sub { color: var(--el-text-color-secondary); font-size: 10.5px; } }
  .band { display: flex; height: 10px; border-radius: 5px; overflow: hidden; gap: 2px; margin-bottom: 10px; i { display: block; } }
  .arow { display: flex; align-items: center; gap: 10px; padding: 5px 0; cursor: pointer; flex-wrap: wrap; border-top: 1px dashed var(--el-border-color);
    .code { padding: 1px 7px; border-radius: 5px; font-weight: 800; font-size: 11px; }
    .nm { min-width: 130px; font-weight: 600; }
    .track { flex: 1; height: 6px; background: var(--el-fill-color-dark); border-radius: 3px; overflow: hidden; i { display: block; height: 100%; border-radius: 3px; } }
    b { width: 90px; text-align: right; } .caret { color: var(--el-text-color-placeholder); }
    .subjects { width: 100%; display: flex; gap: 18px; padding: 4px 0 2px 46px;
      .sj { display: inline-flex; gap: 5px; align-items: baseline; em { font-style: normal; color: var(--el-text-color-secondary); font-size: 10.5px; } } } }
  .up { color: #0ECB81; } .dn { color: #F6465D; } }
.navcards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap: 10px; }
.nc { background: var(--mix-card2,#1E2329); border: 1px solid var(--mix-border,#262B33); border-radius: 8px; padding: 10px 13px; display: flex; flex-direction: column; gap: 2px;
  span { font-size: 11px; color: var(--mix-t3,#5E6673); } b { font-size: 18px; color: var(--mix-t1,#EAECEF); &.hl { color: #F0B90B; } &.bad { color: #F6465D; } } i { font-size: 9.5px; color: var(--mix-t3,#5E6673); font-style: normal; } }
.bridge { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
.bcat { background: var(--mix-panel,#12151A); border: 1px solid var(--mix-border,#262B33); border-radius: 6px; padding: 6px 10px; font-size: 11px;
  span { color: var(--mix-t3,#5E6673); margin-right: 6px; } b.up { color: #0ECB81; } b.down { color: #F6465D; } }
.bsum { display: flex; gap: 16px; flex-wrap: wrap; font-size: 11.5px; color: var(--mix-t2,#848E9C); padding: 8px 0; border-top: 1px solid var(--mix-border,#262B33);
  b { color: var(--mix-t1,#EAECEF); font-variant-numeric: tabular-nums; &.ok { color: #0ECB81; } &.bad { color: #F6465D; } }
  .verdict { font-weight: 700; &.ok { color: #0ECB81; } &.warn { color: #F0B90B; } } }
.hd { display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 700; color: var(--mix-t1,#EAECEF); margin-bottom: 6px; }
.sub { font-size: 10.5px; color: var(--mix-t3,#5E6673); font-weight: 400; }
.fnote { font-size: 10px; color: var(--mix-t3,#5E6673); margin-top: 8px; line-height: 1.6; }
.dimtxt { color: var(--mix-t3,#5E6673); font-size: 10.5px; } .pad { padding: 10px 0; }
.up { color: #0ECB81; } .down { color: #F6465D; } .bad { color: #F6465D !important; } .ok { color: #0ECB81; } .dim { color: var(--mix-t3,#5E6673); }
.fs-CONFIRMED { color: #0ECB81; } .fs-PENDING { color: #F0B90B; } .fs-FAILED { color: #F6465D; }
.brk { font-size: 11px; color: var(--mix-t2,#848E9C); padding: 4px 0; border-bottom: 1px dashed var(--mix-border,#262B33); }
.bk { font-weight: 700; font-size: 9.5px; padding: 1px 6px; border-radius: 4px; background: rgba(246,70,93,.14); color: #F6465D; margin-right: 8px; }
</style>
