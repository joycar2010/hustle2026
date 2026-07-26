<template>
  <div class="mixhist">
    <el-tabs v-model="htab" @tab-change="onTab">
    <!-- V6.1 §7 TradeLifecycleProjection:经济组合一行(默认),原始流水进专家事实页签 -->
    <el-tab-pane label="组合视图(一组合一行)" name="combos">
      <div v-if="symFocus" class="focusbar">已按工作项深链聚焦 <b>{{ symFocus }}</b>
        <a @click="symFocus=''">查看全部 <FIcon name="x" :size="11"/></a></div>
      <div class="combos">
        <div class="crow chead">
          <span class="c-sym">币种</span><span class="c-n">平仓笔数</span><span class="c-v">合计规模</span>
          <span class="c-v">资金费</span><span class="c-v">手续费</span><span class="c-v">利润</span>
          <span class="c-t">最近平仓</span><span class="c-a">展开</span>
        </div>
        <template v-for="c in combos" :key="c.symbol">
          <div class="crow" @click="comboOpen = comboOpen===c.symbol ? '' : c.symbol">
            <span class="c-sym"><b style="color:var(--mix-gold,#F0B90B)">{{ comboOpen===c.symbol?'▾':'▸' }} {{ c.symbol }}</b></span>
            <span class="c-n">{{ c.count }}</span>
            <span class="c-v amtx">{{ fmt(c.notional) }} U</span>
            <span class="c-v" :class="tone(c.funding)">{{ fmtS(c.funding) }}</span>
            <span class="c-v" :class="tone(c.fee)">{{ fmtS(c.fee) }}</span>
            <span class="c-v" :class="tone(c.profit)"><b>{{ fmtS(c.profit) }}</b></span>
            <span class="c-t">{{ c.last }}</span>
            <span class="c-a dim2">逐笔 {{ comboOpen===c.symbol?'收起':'展开' }}</span>
          </div>
          <div v-if="comboOpen===c.symbol" class="cdetail">
            <div v-for="r in c.rows" :key="r.source + r.source_id" class="cdr">
              <span>{{ (r.closed_at||'').slice(5,16) }}</span><span>{{ r.strategy }}</span>
              <span class="amtx">{{ fmt(r.notional) }} U</span>
              <span :class="tone(r.profit)">{{ fmtS(r.profit) }}</span>
              <span class="dim2">{{ r.source }}</span>
            </div>
          </div>
        </template>
        <div v-if="!combos.length" class="empty">该范围无已平仓组合</div>
        <div class="fnote">一行=一个经济组合的全部平仓汇总;点击展开逐笔;原始订单/账单/对账流水见「专家事实」各页签</div>
      </div>
    </el-tab-pane>
    <el-tab-pane label="平仓成交(逐笔)" name="fills">
    <div class="bar">
      <!-- 自定义时间窗（选定后覆盖天数按钮） -->
      <el-date-picker v-model="customRange" type="datetimerange" size="small"
                      range-separator="~" start-placeholder="开始时间" end-placeholder="截止时间"
                      style="max-width:340px" @change="load" />
      <el-radio-group v-model="range" size="small" @change="customRange=null;load()">
        <el-radio-button value="7d">7天</el-radio-button>
        <el-radio-button value="30d">30天</el-radio-button>
        <el-radio-button value="90d">90天</el-radio-button>
        <el-radio-button value="all">全部</el-radio-button>
      </el-radio-group>
      <div class="chips">
        <span class="chip" :class="{on:!strategy}" @click="strategy='';load()">全部</span>
        <span v-for="c in PRODUCTS" :key="c.code" class="chip"
              :class="{on:strategy===c.code}" :style="strategy===c.code?{background:c.colorBg,color:c.color,borderColor:c.color}:{}"
              @click="strategy=c.code;load()">{{ c.ccode }}</span>
      </div>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- 合计统计条（落袋口径） -->
    <div class="statbar">
      <span class="stat"><em>笔数</em><b>{{ stats.count ?? rows.length }}</b></span>
      <span class="stat"><em>合计</em><b class="amtx">{{ fmt(stats.notional) }} U</b></span>
      <span class="stat"><em>资金费</em><b :class="tone(stats.funding)">{{ fmtS(stats.funding) }}</b></span>
      <span class="stat"><em>手续费</em><b :class="tone(stats.fee)">{{ fmtS(stats.fee) }}</b></span>
      <span class="stat"><em>返佣</em><b :class="tone(stats.rebate)">{{ fmtS(stats.rebate) }}</b></span>
      <span class="stat gold"><em>利润</em><b :class="tone(stats.profit)">{{ fmtS(stats.profit) }}</b></span>
      <span class="statnote">{{ stats.note }}</span>
    </div>

    <div class="tbl">
      <div class="tr th">
        <span>策略</span><span>币种</span><span>主账户平台</span><span>主账户</span>
        <span>对冲平台</span><span>对冲账户</span><span class="r">数量</span><span class="r">持仓U</span>
        <span class="r">资金费</span><span class="r">手续费</span><span class="r">返佣</span><span class="r">利润</span>
        <span>终态</span><span>开仓</span><span>平仓</span><span class="r">持仓h</span>
      </div>
      <div v-for="r in rows" :key="r.source + r.source_id" class="tr">
        <span><i class="sb" :style="{background: prodColorBg(r.strategy_code), color: prodColor(r.strategy_code)}">{{ prodCode(r.strategy_code) }}</i></span>
        <span class="sym" style="color:var(--mix-gold,#F0B90B);font-weight:700">{{ r.symbol }}</span>
        <span :class="'vx-'+r.master_venue">{{ r.master_venue }}</span><span class="acct">{{ r.master_account }}</span>
        <span :class="'vx-'+r.hedge_venue">{{ r.hedge_venue }}</span><span class="acct">{{ r.hedge_account }}</span>
        <span class="r">{{ fmt(r.qty) }}</span><span class="r">{{ fmt(r.notional) }}</span>
        <span class="r" :class="tone(r.funding)">{{ fmtS(r.funding) }}</span>
        <span class="r" :class="tone(r.fee)">{{ fmtS(r.fee) }}</span>
        <span class="r" :class="tone(r.rebate)">{{ fmtS(r.rebate) }}</span>
        <span class="r pf" :class="tone(r.profit)">{{ fmtS(r.profit) }}</span>
        <span><i class="st" :class="r.state === 'CLOSED' ? 'ok' : 'bad'">{{ r.state }}</i></span>
        <span class="tm">{{ short(r.opened_at) }}</span><span class="tm">{{ short(r.closed_at) }}</span>
        <span class="r">{{ r.hold_hours ?? '—' }}</span>
      </div>
      <div v-if="!rows.length" class="empty">该范围无平仓记录</div>
    </div>
    <div class="foot">数据=mix_main.trade_history 持久账（S1/S2←dcm 终态行；S3←coin 桥终态透传,300s 汇入）；
      资金费/手续费/返佣/利润=income_records 落袋账单按持有窗归因（S3 账本在 coin 库,暂标 —）</div>
    </el-tab-pane>
    <el-tab-pane v-for="k in FACTS" :key="k.v" :label="k.t" :name="k.v" lazy>
      <div class="fbar">
        <el-input v-model="fsym" size="small" placeholder="按 symbol 筛选" style="width:160px" @change="loadFacts" clearable />
        <el-button size="small" @click="loadFacts">刷新</el-button>
        <span class="dimtxt">{{ facts.length }} 条事实 · 只读不可编辑 · 因果链 Intent→Order→Fill→Bill→Ledger→RECON→NAV</span>
      </div>
      <el-table :data="facts" size="small" stripe max-height="440">
        <el-table-column v-for="col in factCols" :key="col" :label="col" show-overflow-tooltip min-width="90">
          <template #default="{row}"><span :class="[fcCls(col, row[col]), numCls(row[col])]">{{ fmtCell(row[col]) }}</span></template>
        </el-table-column>
      </el-table>
      <div class="dimtxt" style="margin-top:6px">检索键:symbol / venue / owner / trace_id / saga_id / incident_id / maintenance_id;历史事实不可编辑,导出需脱敏。</div>
    </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'
import { STRATEGY_META } from '../../components/PositionTable/types'

const PRODUCTS = Object.values(STRATEGY_META).filter(m => m.code)
const prodCode = code => STRATEGY_META[code]?.ccode || code
const prodColor = code => STRATEGY_META[code]?.color || '#F0B90B'
const prodColorBg = code => STRATEGY_META[code]?.colorBg || 'rgba(240,185,11,.14)'

const rows = ref([]); const stats = ref({}); const range = ref('30d'); const strategy = ref('')
const customRange = ref(null); const loading = ref(false)
const fmt = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))
const fmtS = v => (v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 }))
const tone = v => (v == null ? '' : v >= 0 ? 'up' : 'down')
const short = t => (t ? t.slice(5, 16).replace('T', ' ') : '—')

async function load() {
  loading.value = true
  try {
    const params = { range: range.value, ...(strategy.value ? { strategy: strategy.value } : {}) }
    if (customRange.value?.[0] && customRange.value?.[1]) {
      params.start = new Date(customRange.value[0]).toISOString()
      params.end = new Date(customRange.value[1]).toISOString()
    }
    const r = await mixApi.historyQ(params)
    rows.value = r.rows || []
    stats.value = r.stats || {}
  } catch (e) { ElMessage.error(e?.detail || '加载失败') }
  finally { loading.value = false }
}
const htab = ref('combos')
// V6.2 N3 深链:从工作项进入(?symbol=XXX)自动聚焦该组合
import { useRoute } from 'vue-router'
const _route = useRoute()
const symFocus = ref(String(_route.query.symbol || '').toUpperCase())
// 组合视图:逐笔 rows 按币种聚合(一行=一个经济组合;客户端聚合,不造第二财务口径——数字与逐笔完全同源)
const comboOpen = ref(symFocus.value || '')
const combos = computed(() => {
  const m = {}
  for (const r of rows.value) {
    if (symFocus.value && String(r.symbol || '').toUpperCase() !== symFocus.value) continue
    const s = r.symbol || '?'
    const c = (m[s] = m[s] || { symbol: s, count: 0, notional: 0, funding: 0, fee: 0, profit: 0, last: '', rows: [] })
    c.count++; c.notional += Number(r.notional) || 0
    c.funding += Number(r.funding) || 0; c.fee += Number(r.fee) || 0; c.profit += Number(r.profit) || 0
    const t = (r.closed_at || '').slice(5, 16)
    if (t > c.last) c.last = t
    c.rows.push(r)
  }
  return Object.values(m).sort((a, b) => (b.last > a.last ? 1 : -1))
})
const FACTS = [{v:'orders',t:'专家·订单/成交'},{v:'bills',t:'专家·交易所账单'},{v:'ledger',t:'专家·归一账本'},
  {v:'proposals',t:'专家·交易意图(提案)'},{v:'maintenance',t:'专家·维护事件'},{v:'recon',t:'专家·账目核对断点'}]
const facts = ref([]); const fsym = ref('')
// 专家表通用着色:按列名语义(venue六色/symbol金/金额亮青/盈亏费率符号色/时间淡蓝)
function fcCls(col, v) {
  const c = String(col).toLowerCase()
  if (c.includes('venue')) return 'vx-' + String(v || '').toLowerCase()
  if (c === 'symbol' || c.endsWith('_symbol')) return 'symx'
  if (/(pnl|profit|income|funding|fee|rebate|amount)/.test(c)) { const n = Number(v); return n > 0 ? 'up' : (n < 0 ? 'dn' : '') }
  if (/(qty|notional|price|equity|usdt|units)/.test(c)) return 'amtx'
  if (/(time|_at|ts|date)/.test(c)) return 'timex'
  return ''
}
const factCols = computed(() => facts.value.length ? Object.keys(facts.value[0]) : [])
const fmtCell = v => (v == null ? 'N/A' : typeof v === 'number' ? (Math.abs(v) < 1000 ? v.toFixed(4) : v.toFixed(2)) : String(v))
const numCls = v => (typeof v === 'number' ? (v >= 0 ? 'up' : 'down') : '')
async function loadFacts(){ if(htab.value==='fills'||htab.value==='combos')return; try{ facts.value=(await mixApi.auditFacts(htab.value, fsym.value, 30))?.rows||[] }catch(e){ facts.value=[] } }
function onTab(){ if(htab.value!=='fills') loadFacts() }
onMounted(load)
</script>

<style scoped lang="scss">
.mixhist { display: flex; flex-direction: column; gap: 10px; }
.bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.chips { display: flex; gap: 5px;
  .chip { padding: 2px 9px; border-radius: 6px; border: 1px solid var(--el-border-color); cursor: pointer; font-size: 12px; color: var(--el-text-color-secondary);
    &.on { background: #F0B90B; color: #0B0E11; border-color: #F0B90B; font-weight: 700; } } }
.statbar { display: flex; gap: 18px; align-items: baseline; flex-wrap: wrap; border: 1px solid rgba(240,185,11,.28);
  background: rgba(240,185,11,.05); border-radius: 8px; padding: 8px 14px;
  .stat { display: inline-flex; gap: 6px; align-items: baseline; font-size: 12px;
    em { font-style: normal; color: var(--mix-t3, #5E6673); font-size: 11px; }
    b { font-size: 14px; font-variant-numeric: tabular-nums; }
    &.gold b { font-size: 16px; } }
  .statnote { margin-left: auto; font-size: 10px; color: var(--mix-t3, #5E6673); } }
.tbl { border: 1px solid var(--mix-border, #262B33); border-radius: 8px; overflow: auto; max-height: calc(100vh - 300px); }
.tr { display: grid; grid-template-columns: 42px 96px 78px 116px 78px 132px 76px 70px 74px 74px 60px 78px 70px 90px 90px 52px;
  gap: 6px; padding: 4px 10px; font-size: 11.5px; align-items: center; border-bottom: 1px solid var(--mix-border, #262B33);
  font-variant-numeric: tabular-nums;
  &.th { position: sticky; top: 0; background: var(--mix-panel, #12151A); color: var(--mix-t3, #5E6673); font-weight: 700; z-index: 1; } }
.sym { font-weight: 700; }
.acct { color: var(--mix-t2, #848E9C); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tm { color: var(--mix-t3, #5E6673); }
.r { text-align: right; }
.pf { font-weight: 800; }
.up { color: #0ECB81; } .down { color: #F6465D; }
.sb { font-size: 9.5px; font-weight: 800; color: #0B0E11; border-radius: 3px; padding: 1px 5px; font-style: normal; }
.st { font-size: 10px; border-radius: 3px; padding: 0 5px; font-style: normal;
  &.ok { background: rgba(14,203,129,.15); color: #0ECB81; }
  &.bad { background: rgba(246,70,93,.15); color: #F6465D; } }
.empty { padding: 24px; text-align: center; color: var(--mix-t3, #5E6673); font-size: 12px; }
.combos{display:flex;flex-direction:column}
.crow{display:flex;align-items:center;height:34px;border-bottom:1px solid var(--mix-border,#2B3139);cursor:pointer;gap:4px;min-width:720px}
.crow.chead{height:26px;cursor:default;font-size:10px;color:var(--mix-t3,#5E6673);font-weight:700;background:var(--mix-panel,#12151A)}
.crow span{padding:0 8px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.c-sym{width:130px}.c-n{width:80px}.c-v{width:110px;text-align:right}.c-t{width:110px}.c-a{flex:1;text-align:right}
.cdetail{background:#00000022;border-bottom:1px solid var(--mix-border,#2B3139);padding:4px 0}
.cdr{display:flex;gap:8px;font-size:11px;color:var(--mix-t2,#848E9C);padding:3px 16px}
.cdr span{min-width:90px}
.dim2{color:var(--mix-t3,#5E6673)}
.fnote{font-size:10px;color:var(--mix-t3,#5E6673);padding:8px 4px}
.focusbar{font-size:11px;color:var(--mix-t2,#848E9C);background:#F0B90B14;border:1px solid #F0B90B4D;
  border-radius:6px;padding:6px 12px;margin-bottom:8px}
.focusbar b{color:#F0B90B}
.focusbar a{color:var(--mix-t3,#5E6673);cursor:pointer;margin-left:10px}
.foot { font-size: 10.5px; color: var(--mix-t3, #5E6673); }
.fbar { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.dimtxt { color: var(--el-text-color-secondary); font-size: 10.5px; }
.up { color: #0ECB81; } .down { color: #F6465D; }
.symx{color:var(--mix-gold,#F0B90B);font-weight:700}
</style>
