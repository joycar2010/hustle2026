<template>
  <div>
    <div class="kpis">
      <div class="kpi"><b :class="cls(p.totals && p.totals.net)">{{ fmt(p.totals && p.totals.net) }}</b><span>净PnL({{ p.days }}d)</span></div>
      <div class="kpi"><b class="pos">{{ fmt(p.totals && p.totals.FUNDING) }}</b><span>资金费</span></div>
      <div class="kpi"><b>{{ fmt(p.totals && p.totals.PNL) }}</b><span>已实现盈亏</span></div>
      <div class="kpi"><b class="neg">{{ fmt(p.totals && p.totals.FEE) }}</b><span>手续费</span></div>
    </div>
    <div class="card"><h3>累计净值曲线</h3>
      <div ref="chart" style="height:240px"></div>
      <div v-if="!(p.daily && p.daily.length)" class="dim">暂无逐笔数据(pnl-recorder 拉取中)</div>
    </div>
    <div class="card"><h3>逐所归因</h3>
      <el-table :data="venueRows" size="small" empty-text="暂无">
        <el-table-column prop="venue" label="所" />
        <el-table-column label="资金费"><template #default="s"><span class="pos">{{ fmt(s.row.FUNDING) }}</span></template></el-table-column>
        <el-table-column label="已实现"><template #default="s">{{ fmt(s.row.PNL) }}</template></el-table-column>
        <el-table-column label="手续费"><template #default="s"><span class="neg">{{ fmt(s.row.FEE) }}</span></template></el-table-column>
        <el-table-column label="净"><template #default="s"><span :class="cls(s.row.net)">{{ fmt(s.row.net) }}</span></template></el-table-column>
      </el-table></div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { api } from '../api'
import { fmt, cls } from '../lib'
const p = ref({}); const chart = ref(null); let ec
const venueRows = computed(() => Object.entries(p.value.venues || {}).map(([venue, v]) => ({ venue, ...v })))
onMounted(async () => {
  try { p.value = await api.pnl(30) } catch (e) {}
  await nextTick()
  if (chart.value && p.value.daily && p.value.daily.length) {
    ec = echarts.init(chart.value)
    ec.setOption({
      backgroundColor: 'transparent', grid: { left: 48, right: 16, top: 16, bottom: 28 },
      xAxis: { type: 'category', data: p.value.daily.map(x => x.d.slice(5)), axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#21262d' } }, axisLabel: { color: '#8b949e' } },
      tooltip: { trigger: 'axis' },
      series: [{ type: 'line', data: p.value.daily.map(x => x.cum), areaStyle: { color: 'rgba(88,166,255,0.12)' }, lineStyle: { color: '#58a6ff', width: 2 }, symbol: 'none', name: '累计净值' }],
    })
  }
})
</script>
