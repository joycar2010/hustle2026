<template>
  <div class="mixreport">
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
        <b class="up">+{{ a.total.toLocaleString() }}</b>
        <span class="caret">{{ expanded===a.code ? '⌄' : '›' }}</span>
        <div v-if="expanded===a.code" class="subjects" @click.stop>
          <span v-for="(v,k) in a.subjects" :key="k" class="sj">
            <em>{{ subjectLabel(k) }}</em><b :class="v>=0?'up':'dn'">{{ v>=0?'+':'' }}{{ v.toLocaleString() }}</b>
          </span>
        </div>
      </div>
    </div>
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
onMounted(() => { chart = echarts.init(chartEl.value); window.addEventListener('resize', onResize); load() })
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
</style>
