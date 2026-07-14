<template>
  <div class="aicoin">
    <RiskStatusBar />
    <!-- 研判对象条(yVCmT) -->
    <div class="objbar card">
      <b class="sym">{{ canonSym || '—' }}</b>
      <el-autocomplete v-model="kw" :fetch-suggestions="suggest" placeholder="搜索币种(AiCoin dbKey)"
        size="small" style="width:260px" clearable @select="onPick">
        <template #default="{ item }"><span>{{ item.label }}</span><span class="dimtxt" style="margin-left:8px">{{ item.value }}</span></template>
      </el-autocomplete>
      <i class="tag">{{ symbol }}</i>
      <span class="dimtxt">数据时间 {{ dataTs || 'N/A' }}</span>
      <span class="grow" />
      <el-button size="small" type="warning" plain @click="openAiCoinSite">打开 AiCoin ↗</el-button>
      <el-button size="small" @click="copySym">复制交易对</el-button>
      <el-radio-group v-model="period" size="small" @change="loadK">
        <el-radio-button v-for="p in PERIODS" :key="p.v" :value="p.v">{{ p.t }}</el-radio-button>
      </el-radio-group>
      <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
    </div>
    <!-- 冲突提示黄条(U25tWq):AiCoin vs 官方,无"采用AiCoin数据"选项 -->
    <div class="conflict" v-if="conflict">
      <span class="ct">⚠ 外部参考与官方数据存在差异</span>
      <span class="dimtxt">AiCoin 观察价 {{ conflict.ai }} ｜ 官方可成交价 {{ conflict.official }} ｜ 差异 {{ conflict.pct }}% — 外部参考不可覆盖正式数据,无「采用 AiCoin 数据」选项</span>
      <span class="grow" />
      <el-button size="small" @click="scrollVenues">查看各所报价</el-button>
      <el-button size="small" @click="markAnomaly">标记数据异常</el-button>
      <el-button size="small" type="danger" plain disabled title="逐币冻结走 Eligibility&Quarantine(下批)">冻结该币新增</el-button>
    </div>

    <!-- 主体三栏(N9oM0):左官方快照620 | 中AiCoin观察 | 右人工研判520 -->
    <div class="tri">
      <div class="card lcol" ref="venuesEl">
        <div class="chd2"><b>系统官方快照</b><span class="dimtxt">开仓硬闸唯一数据源</span></div>
        <div class="inds">
          <div class="ind"><span>最优中价</span><b>{{ best?.mid ?? 'N/A' }}</b></div>
          <div class="ind"><span>最窄点差</span><b>{{ bestSpread ?? 'N/A' }} bps</b></div>
          <div class="ind"><span>资金费区间%/d</span><b>{{ fundRange }}</b></div>
          <div class="ind"><span>24h量 / OI</span><b>N/A</b></div>
          <div class="ind"><span>深度±25bps</span><b>N/A</b></div>
          <div class="ind"><span>可借量</span><b>N/A</b></div>
          <div class="ind"><span>上市天数</span><b>N/A</b></div>
          <div class="ind"><span>新鲜所数</span><b>{{ va.filter(v=>v.fresh).length }}/6</b></div>
          <div class="ind"><span>候选E(风调)</span><b>{{ oppE ?? 'N/A' }}</b></div>
        </div>
        <div class="vhead"><span>Venue</span><span>模式</span><span class="r">中价</span><span class="r">点差</span><span class="r">费%/d</span><span>鲜</span></div>
        <div v-for="r in va" :key="r.venue" class="vrow" :class="{stale: !r.fresh}">
          <span><b>{{ r.venue }}</b></span><span :class="'m-'+r.mode">{{ r.mode }}</span>
          <span class="r">{{ r.mid ?? 'N/A' }}</span><span class="r">{{ r.spread_bps ?? '—' }}</span>
          <span class="r">{{ r.funding_daily_pct ?? '—' }}</span><span>{{ r.fresh ? '✓' : '✗' }}</span>
        </div>
      </div>

      <div class="card mcol">
        <div class="chd2"><b>AiCoin 观察区</b><span class="dimtxt">人工参考 · 不进入自动交易链路</span><span class="grow" /><span class="dimtxt">{{ note }}</span></div>
        <div ref="chartEl" class="kchart"></div>
      </div>

      <div class="card rcol">
        <div class="chd2"><b>人工研判表 → LabCase</b><span class="dimtxt">全必填 · 只追加不覆盖</span></div>
        <el-form label-width="96px" size="small" class="labform">
          <el-form-item label="行情结构"><el-select v-model="lab.structure" placeholder="必选">
            <el-option v-for="o in ['放量拉升','缩量阴跌','横盘吸筹','高位派发','事件驱动','无明显结构']" :key="o" :value="o" /></el-select></el-form-item>
          <el-form-item label="控盘置信度"><el-select v-model="lab.confidence" placeholder="仅人工标签,非系统事实">
            <el-option v-for="o in ['高(人工)','中(人工)','低(人工)']" :key="o" :value="o" /></el-select></el-form-item>
          <el-form-item label="预期阶段"><el-select v-model="lab.stage" placeholder="必选">
            <el-option v-for="o in ['启动前','拉升中','出货中','衰竭','不确定']" :key="o" :value="o" /></el-select></el-form-item>
          <el-form-item label="建议产品"><el-select v-model="lab.product" placeholder="必选">
            <el-option v-for="o in ['C1','C2.H','C2.C','C3.S','C3.R','不建议']" :key="o" :value="o" /></el-select></el-form-item>
          <el-form-item label="支持证据"><el-input v-model="lab.evidence_for" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="反对证据"><el-input v-model="lab.evidence_against" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="入场失效"><el-input v-model="lab.invalidation" placeholder="如:费差<6bps 连2期" /></el-form-item>
          <el-form-item label="最晚复核"><el-input v-model="lab.review_by" placeholder="如:07-15 09:00" /></el-form-item>
          <el-form-item label="尾险预算"><el-input v-model="lab.tail_budget" placeholder="如:≤8U(0.6% NAV)" /></el-form-item>
        </el-form>
      </div>
    </div>

    <!-- 历史案件(K3k54) -->
    <div class="card hist">
      <div class="chd2"><b>LAB 历史研判案件 · {{ cases.length }}</b><span class="dimtxt">用于验证人工「币有没有力气」判断的预测价值</span></div>
      <div class="hhead"><span>研判时间</span><span>操作员</span><span>币</span><span>阶段</span><span>建议产品</span><span>动作</span><span>AiCoin/官方价</span><span>复盘结论</span></div>
      <div v-if="!cases.length" class="dimtxt pad">无历史案件</div>
      <div v-for="c in cases" :key="c.id" class="hrow">
        <span>{{ (c.created_at||'').slice(5,16) }}</span><span>{{ c.operator }}</span><span><b>{{ c.symbol }}</b></span>
        <span>{{ c.stage || '—' }}</span><span>{{ c.product || '—' }}</span>
        <span :class="c.action==='REJECT' ? 'bad' : ''">{{ c.action }}</span>
        <span>{{ c.aicoin_price || '—' }} / {{ c.official_price || '—' }}</span>
        <span class="dimtxt">{{ c.outcome || '待复盘' }}</span>
      </div>
    </div>

    <!-- 决策条(PRIgT):系统计算六数 + 无直接开仓 -->
    <div class="card decide">
      <div class="nums">
        <div class="num"><span>建议名义</span><b>{{ oppTarget ?? 'N/A' }}</b></div>
        <div class="num"><span>保守净期望</span><b>{{ oppE ?? 'N/A' }}</b></div>
        <div class="num"><span>最大压力损失</span><b>N/A</b></div>
        <div class="num"><span>最弱退出容量</span><b>N/A</b></div>
        <div class="num"><span>预计开平成本</span><b>N/A</b></div>
        <div class="num"><span>净Delta容差</span><b>±25U</b></div>
      </div>
      <span class="dimtxt flow">无「直接开仓」:观察 → LabCase → 官方补齐 → 经济闸 → 风险闸 → DRY_RUN → 冷静期 → 二次认证 → PositionIntent</span>
      <el-button size="small" :loading="saving==='OBSERVE'" @click="saveCase('OBSERVE')">仅保存观察</el-button>
      <el-button size="small" :loading="saving==='WATCHLIST'" @click="saveCase('WATCHLIST')">加入观察名单</el-button>
      <el-button size="small" type="warning" plain disabled title="DRY_RUN 提案链下批接入">生成 DRY_RUN</el-button>
      <el-button size="small" type="danger" plain :loading="saving==='REJECT'" @click="saveCase('REJECT')">拒绝机会</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const PERIODS = [{ v: '15', t: '15m' }, { v: '60', t: '1h' }, { v: '240', t: '4h' }, { v: '1440', t: '1D' }]
const kw = ref(''); const symbol = ref('btcswapusdt:binance'); const period = ref('60')
const loading = ref(false); const note = ref(''); const dataTs = ref('')
const chartEl = ref(null); const venuesEl = ref(null)
const va = ref([]); const cases = ref([]); const opps = ref([]); const saving = ref('')
const lastClose = ref(null)
const lab = ref({ structure: '', confidence: '', stage: '', product: '', evidence_for: '',
  evidence_against: '', invalidation: '', review_by: '', tail_budget: '' })
let chart = null; let ro = null

const canonSym = computed(() => {
  const m = symbol.value.match(/^([a-z0-9]+?)(swap|perp)?usdt/i)
  return m ? (m[1] + 'USDT').toUpperCase() : symbol.value.toUpperCase()
})
const best = computed(() => va.value.filter(v => v.fresh && v.mid != null)
  .sort((a, b) => (a.spread_bps ?? 999) - (b.spread_bps ?? 999))[0])
const bestSpread = computed(() => best.value?.spread_bps ?? null)
const fundRange = computed(() => {
  const fs = va.value.map(v => v.funding_daily_pct).filter(v => v != null)
  return fs.length ? `${Math.min(...fs)} ~ ${Math.max(...fs)}` : 'N/A'
})
const curOpp = computed(() => opps.value.find(o => o.symbol === canonSym.value))
const oppE = computed(() => (curOpp.value?.risk_adjusted_e_bps != null ? curOpp.value.risk_adjusted_e_bps + ' bps' : null))
const oppTarget = computed(() => (curOpp.value?.target_notional_usdt != null ? curOpp.value.target_notional_usdt + ' U' : null))
const conflict = computed(() => {
  if (lastClose.value == null || best.value?.mid == null) return null
  const pct = Math.abs(lastClose.value - best.value.mid) / best.value.mid * 100
  if (pct < 0.5) return null
  return { ai: lastClose.value, official: best.value.mid, pct: pct.toFixed(2) }
})

async function suggest(q, cb) {
  if (!q) return cb([])
  try {
    const list = await mixApi.aicoinSearch(q)
    cb((list || []).map(c => ({ value: c.db_key || c.dbKey || c.key || '', label: c.show || c.name || c.symbol || '' })).filter(x => x.value))
  } catch (e) { note.value = e?.detail || 'AiCoin 未配置'; cb([]) }
}
function onPick(item) { symbol.value = item.value; loadAll() }
function openAiCoinSite() { copySym(); window.open(`https://www.aicoin.com/zh-Hans/search?keyword=${encodeURIComponent(canonSym.value)}`) }
function copySym() { navigator.clipboard?.writeText(canonSym.value); ElMessage.success(`已复制 ${canonSym.value}`) }
function scrollVenues() { venuesEl.value?.scrollIntoView({ behavior: 'smooth' }) }
async function markAnomaly() {
  try {
    await mixApi.aicoinLabSave({ symbol: canonSym.value, action: 'OBSERVE',
      evidence_against: `标记数据异常:AiCoin ${lastClose.value} vs 官方 ${best.value?.mid}`,
      aicoin_price: String(lastClose.value ?? ''), official_price: String(best.value?.mid ?? '') })
    ElMessage.success('异常观察已登记(LabCase)')
    loadCases()
  } catch (e) { ElMessage.error(e?.detail || '登记失败') }
}
async function saveCase(action) {
  saving.value = action
  try {
    await mixApi.aicoinLabSave({ symbol: canonSym.value, action, ...lab.value,
      aicoin_price: String(lastClose.value ?? ''), official_price: String(best.value?.mid ?? '') })
    ElMessage.success(`LabCase 已保存(${action})`)
    loadCases()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败(研判表全必填)') }
  finally { saving.value = '' }
}
async function loadK() {
  loading.value = true; note.value = ''
  try {
    const r = await mixApi.aicoinKline(symbol.value, period.value, 300)
    const rows = r?.data || []
    if (!rows.length) { note.value = '无K线数据'; return }
    const norm = rows.map(k => Array.isArray(k)
      ? { t: +k[0] * (String(k[0]).length < 13 ? 1000 : 1), o: +k[1], h: +k[2], l: +k[3], c: +k[4], v: +k[5] }
      : { t: +(k.ts || k.time || k.id) * (String(k.ts || k.time || k.id).length < 13 ? 1000 : 1),
          o: +k.open, h: +k.high, l: +k.low, c: +k.close, v: +(k.volume ?? k.vol ?? 0) })
    lastClose.value = norm[norm.length - 1].c
    dataTs.value = new Date(norm[norm.length - 1].t).toLocaleString('zh')
    chart.setOption({
      backgroundColor: 'transparent',
      grid: [{ left: 58, right: 14, top: 10, height: '64%' }, { left: 58, right: 14, top: '80%', height: '14%' }],
      xAxis: [
        { type: 'category', data: norm.map(k => new Date(k.t).toLocaleString('zh', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })),
          axisLine: { lineStyle: { color: '#262B33' } }, axisLabel: { color: '#5E6673', fontSize: 10 } },
        { type: 'category', gridIndex: 1, data: norm.map(k => k.t), show: false },
      ],
      yAxis: [{ scale: true, splitLine: { lineStyle: { color: '#1E2329' } }, axisLabel: { color: '#5E6673', fontSize: 10 } },
        { gridIndex: 1, show: false }],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 55, end: 100 }],
      tooltip: { trigger: 'axis', backgroundColor: '#181B21', borderColor: '#262B33', textStyle: { color: '#EAECEF', fontSize: 11 } },
      series: [
        { type: 'candlestick', data: norm.map(k => [k.o, k.c, k.l, k.h]),
          itemStyle: { color: '#0ECB81', color0: '#F6465D', borderColor: '#0ECB81', borderColor0: '#F6465D' } },
        { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: norm.map(k => k.v), itemStyle: { color: '#3a4150' } },
      ],
    })
    note.value = `${norm.length} 根 · 收 ${lastClose.value}`
  } catch (e) { note.value = e?.detail || 'K线拉取失败(AiCoin 未配置?)' } finally { loading.value = false }
}
async function loadCases() { try { cases.value = (await mixApi.aicoinLabList())?.rows || [] } catch (e) { /* */ } }
async function loadAll() {
  loadK()
  try { va.value = (await mixApi.riskSymbolAnalysis(canonSym.value))?.venues || [] } catch (e) { va.value = [] }
  try { opps.value = (await mixApi.riskOpportunities())?.candidates || [] } catch (e) { /* */ }
  loadCases()
}
onMounted(() => {
  chart = echarts.init(chartEl.value)
  ro = new ResizeObserver(() => chart && chart.resize()); ro.observe(chartEl.value)
  loadAll()
})
onUnmounted(() => { ro && ro.disconnect(); chart && chart.dispose() })
</script>

<style scoped lang="scss">
.aicoin { display: flex; flex-direction: column; gap: 10px; min-height: 100%; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; min-width: 0; }
.chd2 { font-size: 12px; font-weight: 700; color: var(--mix-t1, #EAECEF); padding: 10px 14px 6px; display: flex; align-items: center; gap: 8px; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.pad { padding: 6px 14px 10px; }
.bad { color: #F6465D; }
.objbar { display: flex; align-items: center; gap: 10px; padding: 9px 14px; flex-wrap: wrap;
  .sym { font-size: 17px; color: var(--mix-t1, #EAECEF); } }
.tag { font-style: normal; font-size: 10px; background: var(--mix-card2, #1E2329); border-radius: 4px; padding: 2px 8px; color: var(--mix-t2, #848E9C); }
.conflict { display: flex; align-items: center; gap: 10px; padding: 7px 14px; border-radius: 8px; flex-wrap: wrap;
  background: rgba(240,185,11,.08); border: 1px solid rgba(240,185,11,.3);
  .ct { color: #F0B90B; font-weight: 700; font-size: 12px; } }
.tri { flex: 1; display: grid; grid-template-columns: 620px minmax(0,1fr) 520px; gap: 10px; min-height: 460px;
  @media (max-width: 1700px) { grid-template-columns: 420px minmax(0,1fr) 420px; } }
.lcol, .mcol, .rcol { display: flex; flex-direction: column; overflow: hidden; }
.inds { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 2px 14px 8px; }
.ind { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 6px; padding: 6px 9px;
  display: flex; flex-direction: column; gap: 1px;
  span { font-size: 9.5px; color: var(--mix-t3, #5E6673); }
  b { font-size: 12px; color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; } }
.vhead, .vrow { display: grid; grid-template-columns: 86px 100px 1fr 60px 70px 34px; font-size: 10.5px; align-items: center; padding: 0 14px; }
.vhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 20px; border-bottom: 1px solid var(--mix-border, #262B33); }
.vrow { height: 26px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); } &.stale { opacity: .5; } }
.r { text-align: right; padding-right: 8px; font-variant-numeric: tabular-nums; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
.kchart { flex: 1; min-height: 380px; }
.labform { padding: 0 14px 8px; overflow-y: auto; }
.hist { padding-bottom: 6px; }
.hhead, .hrow { display: grid; grid-template-columns: 92px 88px 96px 80px 76px 88px 150px minmax(0,1fr);
  font-size: 10.5px; align-items: center; padding: 0 14px; }
.hhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 20px; border-bottom: 1px solid var(--mix-border, #262B33); }
.hrow { height: 26px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); } }
.decide { display: flex; align-items: center; gap: 10px; padding: 9px 14px; flex-wrap: wrap; }
.nums { display: flex; gap: 16px; }
.num { display: flex; flex-direction: column; gap: 1px;
  span { font-size: 9.5px; color: var(--mix-t3, #5E6673); }
  b { font-size: 12.5px; color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; } }
.flow { max-width: 380px; }
</style>
