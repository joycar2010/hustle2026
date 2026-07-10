<template>
  <div>
    <div class="kpis">
      <div class="kpi"><b :class="cls(o.pnl && o.pnl.net_total)">{{ fmt(o.pnl && o.pnl.net_total) }}</b><span>累计净PnL</span></div>
      <div class="kpi"><b>{{ o.reconcile && o.reconcile.total_equity_usdt }}</b><span>实盘权益</span></div>
      <div class="kpi"><b>{{ (o.open_positions || []).length }}</b><span>在场配对</span></div>
      <div class="kpi"><b :class="o.alerts_this_round ? 'neg' : 'pos'">{{ o.alerts_this_round }}</b><span>本轮告警</span></div>
      <div class="kpi"><b>{{ svcok }}/{{ (o.services || []).length }}</b><span>服务在线</span></div>
      <div class="kpi"><b><el-tag :type="o.mode === 'armed' ? 'danger' : 'info'">{{ o.mode }}</el-tag></b><span>引擎模式</span></div>
    </div>
    <div class="card"><h3>服务健康</h3>
      <el-table :data="o.services" size="small">
        <el-table-column label="服务"><template #default="s"><span class="dot" :class="'s-' + s.row.state"></span>{{ s.row.name }}</template></el-table-column>
        <el-table-column prop="state" label="状态" width="90" /><el-table-column prop="age" label="心跳(s)" width="90" />
      </el-table></div>
    <div class="card"><h3>在场配对 + 风控护栏</h3>
      <el-table :data="(o.guards && o.guards.pairs) || []" size="small" empty-text="无在场配对">
        <el-table-column prop="symbol" label="币" />
        <el-table-column label="venue"><template #default="s">{{ s.row.venue_long }}/{{ s.row.venue_short }}</template></el-table-column>
        <el-table-column label="多腿距强平%"><template #default="s">{{ fmt(s.row.dist_liq && s.row.dist_liq.long, 1) }}</template></el-table-column>
        <el-table-column label="空腿距强平%"><template #default="s">{{ fmt(s.row.dist_liq && s.row.dist_liq.short, 1) }}</template></el-table-column>
        <el-table-column label="配对浮亏"><template #default="s"><span :class="cls(pairUpnl(s.row))">{{ s.row.upnl ? fmt(pairUpnl(s.row), 4) : '–' }}</span></template></el-table-column>
      </el-table></div>
    <div class="card"><h3>各所权益 + 保证金水位</h3>
      <el-table :data="o.waterline || []" size="small">
        <el-table-column prop="venue" label="所" />
        <el-table-column label="权益"><template #default="s">{{ fmt(s.row.equity) }}</template></el-table-column>
        <el-table-column label="在场名义"><template #default="s">{{ fmt(s.row.pos_notional) }}</template></el-table-column>
        <el-table-column label="有效杠杆"><template #default="s"><span :class="s.row.leverage > 4 ? 'neg' : ''">{{ fmt(s.row.leverage, 2) }}x</span></template></el-table-column>
      </el-table></div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { fmt, cls } from '../lib'
const o = ref({}); let t
const svcok = computed(() => (o.value.services || []).filter(s => s.state === 'ok').length)
const pairUpnl = (r) => (r.upnl ? (+r.upnl.long + +r.upnl.short) : 0)
async function tick() { try { o.value = await api.overview() } catch (e) {} }
onMounted(() => { tick(); t = setInterval(tick, 5000) })
onUnmounted(() => clearInterval(t))
</script>
