<template>
  <div class="mixhist">
    <div class="bar">
      <el-radio-group v-model="range" size="small" @change="load">
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
      <span class="sum">{{ rows.length }} 条 · 名义合计 {{ totalNotional.toLocaleString() }}U</span>
    </div>

    <div class="tbl">
      <div class="tr th">
        <span>策略</span><span>币种</span><span>主账户平台</span><span>主账户</span>
        <span>对冲平台</span><span>对冲账户</span><span class="r">数量</span><span class="r">名义U</span>
        <span>终态</span><span>开仓</span><span>平仓</span><span class="r">持仓h</span>
      </div>
      <div v-for="r in rows" :key="r.source + r.source_id" class="tr">
        <span><i class="sb" :style="{background: SC[r.strategy_code]}">{{ r.strategy_code }}</i></span>
        <span class="sym">{{ r.symbol }}</span>
        <span>{{ r.master_venue }}</span><span class="acct">{{ r.master_account }}</span>
        <span>{{ r.hedge_venue }}</span><span class="acct">{{ r.hedge_account }}</span>
        <span class="r">{{ fmt(r.qty) }}</span><span class="r">{{ fmt(r.notional) }}</span>
        <span><i class="st" :class="r.state === 'CLOSED' ? 'ok' : 'bad'">{{ r.state }}</i></span>
        <span class="tm">{{ short(r.opened_at) }}</span><span class="tm">{{ short(r.closed_at) }}</span>
        <span class="r">{{ r.hold_hours ?? '—' }}</span>
      </div>
      <div v-if="!rows.length" class="empty">该范围无平仓记录</div>
    </div>
    <div class="foot">数据=mix_main.trade_history 持久账（S1/S2←dcm 终态行；S3←coin 桥终态透传,300s 汇入;mix 独立留存）</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

const SC = { S1: '#4A9CFF', S2: '#F0B90B', S3: '#A78BFA', S4: '#2DD4BF', S5: '#FF9F43', S6: '#F472B6' }
const rows = ref([]); const range = ref('30d'); const strategy = ref(''); const loading = ref(false)
const totalNotional = computed(() => Math.round(rows.value.reduce((n, r) => n + (r.notional || 0), 0)))
const fmt = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))
const short = t => (t ? t.slice(5, 16).replace('T', ' ') : '—')

async function load() {
  loading.value = true
  try { rows.value = await mixApi.history(range.value, strategy.value) }
  catch (e) { ElMessage.error(e?.detail || '加载失败') }
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
.sum { font-size: 11.5px; color: var(--el-text-color-secondary); }
.tbl { border: 1px solid var(--mix-border, #262B33); border-radius: 8px; overflow: auto; max-height: calc(100vh - 250px); }
.tr { display: grid; grid-template-columns: 46px 100px 86px 130px 86px 150px 90px 80px 76px 96px 96px 60px;
  gap: 6px; padding: 4px 10px; font-size: 11.5px; align-items: center; border-bottom: 1px solid var(--mix-border, #262B33);
  &.th { position: sticky; top: 0; background: var(--mix-panel, #12151A); color: var(--mix-t3, #5E6673); font-weight: 700; z-index: 1; } }
.sym { font-weight: 700; }
.acct { color: var(--mix-t2, #848E9C); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tm { color: var(--mix-t3, #5E6673); }
.r { text-align: right; }
.sb { font-size: 9.5px; font-weight: 800; color: #0B0E11; border-radius: 3px; padding: 1px 5px; font-style: normal; }
.st { font-size: 10px; border-radius: 3px; padding: 0 5px; font-style: normal;
  &.ok { background: rgba(14,203,129,.15); color: #0ECB81; }
  &.bad { background: rgba(246,70,93,.15); color: #F6465D; } }
.empty { padding: 24px; text-align: center; color: var(--mix-t3, #5E6673); font-size: 12px; }
.foot { font-size: 10.5px; color: var(--mix-t3, #5E6673); }
</style>
