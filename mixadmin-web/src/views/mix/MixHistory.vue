<template>
  <div class="mixhist">
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
        <span v-for="c in ['S1','S2','S3','S4','S5','S6']" :key="c" class="chip"
              :class="{on:strategy===c}" :style="strategy===c?{background:SC[c],color:'#0B0E11',borderColor:SC[c]}:{}"
              @click="strategy=c;load()">{{ c }}</span>
      </div>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </div>

    <!-- 合计统计条（落袋口径） -->
    <div class="statbar">
      <span class="stat"><em>笔数</em><b>{{ stats.count ?? rows.length }}</b></span>
      <span class="stat"><em>合计</em><b>{{ fmt(stats.notional) }} U</b></span>
      <span class="stat"><em>资金费</em><b :class="tone(stats.funding)">{{ fmtS(stats.funding) }}</b></span>
      <span class="stat"><em>手续费</em><b :class="tone(stats.fee)">{{ fmtS(stats.fee) }}</b></span>
      <span class="stat"><em>返佣</em><b :class="tone(stats.rebate)">{{ fmtS(stats.rebate) }}</b></span>
      <span class="stat gold"><em>利润</em><b :class="tone(stats.profit)">{{ fmtS(stats.profit) }}</b></span>
      <span class="statnote">{{ stats.note }}</span>
    </div>

    <div class="tbl">
      <div class="tr th">
        <span>策略</span><span>币种</span><span>主账户平台</span><span>主账户</span>
        <span>对冲平台</span><span>对冲账户</span><span class="r">数量</span><span class="r">名义U</span>
        <span class="r">资金费</span><span class="r">手续费</span><span class="r">返佣</span><span class="r">利润</span>
        <span>终态</span><span>开仓</span><span>平仓</span><span class="r">持仓h</span>
      </div>
      <div v-for="r in rows" :key="r.source + r.source_id" class="tr">
        <span><i class="sb" :style="{background: SC[r.strategy_code]}">{{ r.strategy_code }}</i></span>
        <span class="sym">{{ r.symbol }}</span>
        <span>{{ r.master_venue }}</span><span class="acct">{{ r.master_account }}</span>
        <span>{{ r.hedge_venue }}</span><span class="acct">{{ r.hedge_account }}</span>
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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

const SC = { S1: '#4A9CFF', S2: '#F0B90B', S3: '#A78BFA', S4: '#2DD4BF', S5: '#FF9F43', S6: '#F472B6' }
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
.foot { font-size: 10.5px; color: var(--mix-t3, #5E6673); }
</style>
