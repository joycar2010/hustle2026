<template>
  <div class="aicoin">
    <RiskStatusBar />
    <div class="card">
      <div class="chd">行情研判 · AiCoin
        <span class="dimtxt">数据权威顺序:交易所官方/A-data ＞ 系统计算 ＞ AiCoin 人工参考(仅研判,不入开仓硬闸)</span>
        <span class="grow" />
        <el-link @click="$router.push('/mix/system')">AiCoin 配置 →</el-link>
      </div>
      <div class="bar2">
        <el-autocomplete v-model="kw" :fetch-suggestions="suggest" placeholder="搜索币种(如 BTC / btcswapusdt:binance)"
          size="small" style="width:300px" clearable @select="onPick">
          <template #default="{ item }">
            <span>{{ item.label }}</span><span class="dimtxt" style="margin-left:8px">{{ item.value }}</span>
          </template>
        </el-autocomplete>
        <el-radio-group v-model="period" size="small" @change="loadK">
          <el-radio-button v-for="p in PERIODS" :key="p.v" :value="p.v">{{ p.t }}</el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="loading" @click="loadK">刷新</el-button>
        <span class="dimtxt">{{ note }}</span>
      </div>
      <div ref="chartEl" class="kchart"></div>
    </div>
    <div class="card fnote2">
      规约:AiCoin 数据为人工研判参考——工作流=观察→LabCase→官方数据补齐→经济闸→风险闸→DRY_RUN→冷静期→二次认证→PositionIntent;
      本页无直接开仓;冲突时只可[查看各所报价][标记异常][冻结新增],无"采用AiCoin数据"入口。
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const PERIODS = [{ v: '1', t: '1m' }, { v: '15', t: '15m' }, { v: '60', t: '1h' },
  { v: '240', t: '4h' }, { v: '1440', t: '1D' }]
const kw = ref('')
const symbol = ref('btcswapusdt:binance')
const period = ref('60')
const loading = ref(false)
const note = ref('')
const chartEl = ref(null)
let chart = null

async function suggest(q, cb) {
  if (!q) return cb([])
  try {
    const list = await mixApi.aicoinSearch(q)
    cb((list || []).map(c => ({ value: c.db_key || c.dbKey || c.key || '', label: c.show || c.name || c.symbol || '' }))
      .filter(x => x.value))
  } catch (e) { note.value = e?.detail || 'AiCoin 未配置'; cb([]) }
}
function onPick(item) { symbol.value = item.value; loadK() }

async function loadK() {
  loading.value = true; note.value = ''
  try {
    const r = await mixApi.aicoinKline(symbol.value, period.value, 300)
    const rows = r?.data || []
    if (!rows.length) { note.value = '无数据(检查 symbol 格式,如 btcswapusdt:binance)'; return }
    // AiCoin kline 行: [ts, open, high, low, close, vol] 或对象
    const norm = rows.map(k => Array.isArray(k)
      ? { t: +k[0] * (String(k[0]).length < 13 ? 1000 : 1), o: +k[1], h: +k[2], l: +k[3], c: +k[4], v: +k[5] }
      : { t: +(k.ts || k.time || k.id) * (String(k.ts || k.time || k.id).length < 13 ? 1000 : 1),
          o: +k.open, h: +k.high, l: +k.low, c: +k.close, v: +(k.volume ?? k.vol ?? 0) })
    chart.setOption({
      backgroundColor: 'transparent',
      grid: [{ left: 60, right: 16, top: 12, height: '62%' }, { left: 60, right: 16, top: '78%', height: '16%' }],
      xAxis: [
        { type: 'category', data: norm.map(k => new Date(k.t).toLocaleString('zh', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })),
          axisLine: { lineStyle: { color: '#262B33' } }, axisLabel: { color: '#5E6673', fontSize: 10 } },
        { type: 'category', gridIndex: 1, data: norm.map(k => k.t), show: false },
      ],
      yAxis: [
        { scale: true, splitLine: { lineStyle: { color: '#1E2329' } }, axisLabel: { color: '#5E6673', fontSize: 10 } },
        { gridIndex: 1, show: false },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 55, end: 100 }],
      tooltip: { trigger: 'axis', backgroundColor: '#181B21', borderColor: '#262B33', textStyle: { color: '#EAECEF', fontSize: 11 } },
      series: [
        { type: 'candlestick', data: norm.map(k => [k.o, k.c, k.l, k.h]),
          itemStyle: { color: '#0ECB81', color0: '#F6465D', borderColor: '#0ECB81', borderColor0: '#F6465D' } },
        { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: norm.map(k => k.v),
          itemStyle: { color: '#3a4150' } },
      ],
    })
    note.value = `${symbol.value} · ${norm.length} 根 · 最新 ${norm[norm.length - 1].c}`
  } catch (e) {
    note.value = e?.detail || e?.error || 'K线拉取失败(AiCoin 未配置?)'
  } finally { loading.value = false }
}

let ro = null
onMounted(() => {
  chart = echarts.init(chartEl.value)
  ro = new ResizeObserver(() => chart && chart.resize())
  ro.observe(chartEl.value)
  loadK()
})
onUnmounted(() => { ro && ro.disconnect(); chart && chart.dispose() })
</script>

<style scoped lang="scss">
.aicoin { display: flex; flex-direction: column; gap: 10px; height: 100%;
  > .card:nth-of-type(1) { flex: 1; display: flex; flex-direction: column; min-height: 0; } }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; padding: 10px 12px; }
.chd { font-size: 12.5px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.bar2 { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.kchart { flex: 1; min-height: 420px; }
.fnote2 { font-size: 10.5px; color: var(--mix-t3, #5E6673); }
</style>
