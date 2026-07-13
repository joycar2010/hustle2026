<template>
  <div class="mo" :style="{ background: 'var(--mix-bg)' }">
    <!-- 品牌行（CMS 区块 user_brand 可配,留空=站点默认） -->
    <div class="brand">
      <span class="logo"><img v-if="cms.logo" :src="cms.logo" class="logoimg" /><template v-else>📈</template></span>
      <b>{{ cms.name || 'HustleCoin' }} <i class="mix-gold">{{ cms.accent || 'Mix' }}</i></b>
      <span class="slogan hidden md:inline">{{ cms.slogan || '把复杂的事，交给系统；把结果，交给你' }}</span>
      <span class="pill">{{ cms.pill || '币安生态风格 · 透明 · 稳健 · 长期主义' }}</span>
    </div>

    <!-- Hero：累计收益（合并） -->
    <div class="hero">
      <div class="lbl">累计收益 (合并) <i class="live">● 实时更新中</i></div>
      <div class="num mix-hero-num">+{{ fmt(summary.total) }} <em>USDT</em></div>
      <div class="trip">
        <div v-for="t in [['今日收益',summary.today],['本周收益',summary.week],['累计收益',summary.total]]" :key="t[0]" class="mix-card cell">
          <em>{{ t[0] }}</em><b class="mix-up">+{{ fmt(t[1]) }}</b><i>USDT</i>
        </div>
      </div>
    </div>

    <!-- 收益趋势：柱形 / 线形切换 + 日/周/月 + 范围 -->
    <div class="mix-card chartbox">
      <div class="ctl">
        <b>收益趋势</b>
        <div class="segs">
          <span v-for="t in ['柱形图','线形图']" :key="t" class="seg" :class="{'mix-chip-on':chartType===t}" @click="chartType=t">{{ t }}</span>
        </div>
        <div class="segs">
          <span v-for="g in ['日','周','月']" :key="g" class="seg" :class="{'mix-chip-on':gran===g}" @click="gran=g">{{ g }}</span>
        </div>
        <div class="segs">
          <span v-for="r in ['30天','90天','半年','全部']" :key="r" class="seg" :class="{'mix-chip-on':range===r}" @click="range=r">{{ r }}</span>
        </div>
      </div>
      <div class="cwrap">
        <Bar v-if="chartType==='柱形图'" :data="barData" :options="barOpts" />
        <Line v-else :data="lineData" :options="lineOpts" />
      </div>
    </div>

    <div class="cols">
      <!-- 怎么赚的（6 类收益来源） -->
      <div class="mix-card sources">
        <div class="hd"><b>怎么赚的</b><em>（人话版 · 6 类收益来源）</em></div>
        <div v-for="s in sources" :key="s.key" class="srow">
          <div class="txt"><b>{{ s.name }}</b>
            <div class="track"><i :style="{ width: (s.share*250)+'%', background: 'var(--mix-accent)' }" /></div>
          </div>
          <b class="pct mix-gold">{{ Math.round(s.share*100) }}%</b>
        </div>
        <div class="ft">贡献占比会随市场变化，收益来源更多元、更稳健</div>
      </div>

      <!-- 我的子账户（合并统计） -->
      <div class="mix-card subacct">
        <div class="hd"><b>我的子账户</b><em>（合并统计）</em></div>
        <div v-for="a in accounts" :key="a.venue" class="arow">
          <b class="v">{{ a.venue }}</b>
          <span class="p"><em>资产</em><b>{{ fmt(a.asset) }}</b></span>
          <span class="p"><em>今日</em><b class="mix-up">+{{ fmt(a.today) }}</b></span>
          <span class="p"><em>累计</em><b class="mix-up">+{{ fmt(a.total) }}</b></span>
        </div>
        <div class="ft">只展示你的合并收益；同一用户名下所有子账户合并为一条净值曲线</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Bar, Line } from 'vue-chartjs'
import { Chart, BarElement, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Filler } from 'chart.js'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import { mixApi } from '@/services/mixApi.js'

Chart.register(BarElement, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Filler, ChartDataLabels)

const summary = ref({ today: 0, week: 0, total: 0 })
const daily = ref([])
const sources = ref([])
const accounts = ref([])
const cms = ref({})   // 品牌头 CMS 区块(官网管理→用户端·品牌头)
const chartType = ref('柱形图')
const gran = ref('日')
const range = ref('30天')

const fmt = n => (n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** 周/月前端聚合日粒度（契约约定） */
const points = computed(() => {
  const rows = daily.value
  if (gran.value === '日') return rows.map(r => ({ label: r.date.slice(5), v: r.net }))
  const b = new Map()
  for (const r of rows) {
    const d = new Date(r.date)
    const k = gran.value === '周' ? `W${Math.ceil(((d - new Date(d.getFullYear(),0,1))/864e5 + 1)/7)}` : r.date.slice(0, 7)
    b.set(k, (b.get(k) || 0) + r.net)
  }
  return [...b].map(([label, v]) => ({ label, v }))
})

const barData = computed(() => ({
  labels: points.value.map(p => p.label),
  datasets: [{
    data: points.value.map(p => p.v),
    backgroundColor: points.value.map(p => p.v >= 0 ? '#0ECB81' : '#F6465D'),
    borderRadius: 3, maxBarThickness: 26,
  }],
}))
const barOpts = {
  responsive: true, maintainAspectRatio: false,
  plugins: {
    datalabels: {
      color: ctx => ctx.dataset.data[ctx.dataIndex] >= 0 ? '#0ECB81' : '#F6465D',
      anchor: ctx => ctx.dataset.data[ctx.dataIndex] >= 0 ? 'end' : 'start',
      align: ctx => ctx.dataset.data[ctx.dataIndex] >= 0 ? 'end' : 'start',
      font: { size: 9 },
      formatter: v => Math.abs(v) >= 400 ? (Math.abs(v) >= 1000 ? (v/1000).toFixed(1)+'k' : v) : '',
    },
  },
  scales: {
    x: { grid: { display: false }, ticks: { color: '#5E6673', maxTicksLimit: 8 } },
    y: { grid: { color: 'rgba(94,102,115,.15)' }, ticks: { color: '#5E6673' } },
  },
}
const lineData = computed(() => {
  let acc = 0
  return {
    labels: points.value.map(p => p.label),
    datasets: [{
      data: points.value.map(p => (acc += p.v)),
      borderColor: '#FCD535', borderWidth: 2.5, pointRadius: 0, fill: true, tension: .35,
      backgroundColor: ctx => {
        const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 260)
        g.addColorStop(0, 'rgba(240,185,11,.35)'); g.addColorStop(1, 'rgba(240,185,11,0)')
        return g
      },
    }],
  }
})
const lineOpts = { ...barOpts, plugins: { datalabels: { display: false } } }

onMounted(async () => {
  mixApi.siteConfig().then(c => { cms.value = (c.blocks || {}).user_brand || {} }).catch(() => { /* 默认 */ })
  ;[summary.value, daily.value, sources.value, accounts.value] = await Promise.all([
    mixApi.earningsSummary('merged'),   // 口径显式：用户端首页 = merged
    mixApi.earningsDaily(),
    mixApi.earningsSources(),
    mixApi.subaccounts('merged'),
  ])
})
</script>

<style scoped>
.mo { min-height: 100vh; padding: 14px 16px 20px; display: flex; flex-direction: column; gap: 14px; color: var(--mix-t1); }
.brand { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.brand .logo { width: 30px; height: 30px; border-radius: 8px; background: linear-gradient(135deg,#FCD535,#F0B90B); display: inline-flex; align-items: center; justify-content: center; overflow: hidden; }
.brand .logoimg { width: 100%; height: 100%; object-fit: contain; }
.brand b { font-size: 17px; } .brand i { font-style: normal; }
.brand .slogan { color: var(--mix-t2); font-size: 11px; }
.brand .pill { margin-left: auto; border: 1px solid rgba(240,185,11,.35); color: var(--mix-accent); border-radius: 16px; padding: 3px 12px; font-size: 11px; background: rgba(240,185,11,.06); }
.hero .lbl { color: var(--mix-t2); font-size: 13px; }
.hero .live { font-style: normal; color: var(--mix-green); font-size: 10.5px; margin-left: 8px; }
.hero .num { font-size: clamp(30px, 6vw, 52px); }
.hero .num em { font-style: normal; font-size: 14px; color: var(--mix-green); background: rgba(14,203,129,.14); border-radius: 5px; padding: 2px 8px; vertical-align: middle; }
.trip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px; }
.trip .cell { padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; }
.trip em { font-style: normal; color: var(--mix-t2); font-size: 11px; }
.trip b { font-size: 16px; } .trip i { font-style: normal; color: var(--mix-t3); font-size: 9px; }
.chartbox { padding: 12px 14px; }
.ctl { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.ctl b { font-size: 13px; margin-right: auto; }
.segs { display: inline-flex; gap: 2px; background: var(--mix-panel); border: 1px solid var(--mix-border); border-radius: 7px; padding: 2px; }
.seg { padding: 2px 9px; border-radius: 5px; font-size: 11px; color: var(--mix-t2); cursor: pointer; }
.cwrap { height: 280px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 768px) { .cols { grid-template-columns: 1fr; } }
.sources, .subacct { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.hd b { font-size: 14px; } .hd em { font-style: normal; color: var(--mix-t2); font-size: 11px; }
.srow { display: flex; align-items: center; gap: 14px; }
.srow .txt { flex: 1; } .srow .txt b { font-size: 12.5px; }
.track { height: 5px; background: var(--mix-card2); border-radius: 3px; margin-top: 5px; overflow: hidden; }
.track i { display: block; height: 100%; border-radius: 3px; }
.pct { font-size: 20px; }
.arow { display: flex; align-items: center; gap: 12px; background: var(--mix-panel); border-radius: 8px; padding: 8px 12px; }
.arow .v { min-width: 70px; font-size: 13px; }
.arow .p { flex: 1; display: flex; flex-direction: column; align-items: flex-end; }
.arow .p em { font-style: normal; color: var(--mix-t3); font-size: 9.5px; }
.arow .p b { font-size: 12.5px; }
.ft { color: var(--mix-t3); font-size: 10.5px; }
</style>
