<template>
  <div class="mixmon">
    <div class="grid">
      <!-- 账户余额水位预警（建议动作感知充提通道） -->
      <div class="card gold">
        <div class="hd"><b>账户余额水位预警</b><el-tag size="small" type="danger" effect="dark">{{ warnCount }} 预警</el-tag></div>
        <div v-for="w in watermarks" :key="w.account" class="wrow">
          <span class="nm">{{ w.account }}<em>{{ w.venue }}</em></span>
          <span class="amt">{{ w.available }}</span>
          <span class="bar"><i :style="{ width: (w.level*100)+'%', background: levelColor(w) }" /></span>
          <span class="th" :style="{ color: levelColor(w) }">{{ thLabel(w) }}</span>
          <el-button v-if="w.suggestion" size="small" :type="w.suggestion.feasible?'warning':'info'" :disabled="!w.suggestion.feasible"
                     @click="createOrder(w)">{{ w.suggestion.text }}</el-button>
        </div>
        <div class="ft">两级阈值：补仓线 20% / 提现线 8% · 通道维护时建议动作自动置灰</div>
      </div>

      <!-- 币种利差监控（1:1 dashboard 利差模块） -->
      <div class="card">
        <div class="hd"><b>币种利差</b><span class="sub">开/平点差 · 资金费 · 日息 · 净利差</span></div>
        <div class="srow head"><span>币种</span><span>开点差</span><span>平点差</span><span>资金费</span><span>日息</span><span>净利差</span><span>状态</span></div>
        <div v-for="s in spreads" :key="s.symbol" class="srow">
          <span class="sym">{{ s.symbol }}</span>
          <span :class="sign(s.open)">{{ s.open }}</span>
          <span :class="sign(s.close)">{{ s.close }}</span>
          <span :class="sign(s.funding)">{{ s.funding }}</span>
          <span class="acc">{{ s.dailyRate }}</span>
          <b :class="sign(s.net)">{{ s.net }}</b>
          <el-tag size="small" :type="s.status==='可开'?'success':s.status==='不可'?'danger':'info'" effect="plain">{{ s.status }}</el-tag>
        </div>
      </div>

      <!-- 进程心跳 + 数据新鲜度 + 借币红线 -->
      <div class="card">
        <div class="hd"><b>进程心跳</b><span class="sub">Redis 真相源 · strategy_proc</span></div>
        <div v-for="h in heartbeats" :key="h.proc+h.shard" class="hrow">
          <i class="dot" :class="{ok:h.ok}" /><span class="nm">{{ h.proc }}</span><em>{{ h.shard }}</em><span class="age">{{ h.age }}</span>
        </div>
        <div class="hd mt"><b>数据新鲜度看门狗</b></div>
        <div class="hrow"><i class="dot ok" /><span class="nm">stale 停更(逐币)</span><span class="age">{{ freshness.stale?.count }} / {{ freshness.stale?.of }} 流</span></div>
        <div class="hrow"><i class="dot ok" /><span class="nm">frozen 半开冻结</span><span class="age">{{ freshness.frozen?.shards }} 分片</span></div>
        <div class="hrow" v-for="d in freshness.divergent||[]" :key="d.symbol">
          <i class="dot warn" /><span class="nm">divergent · {{ d.symbol }}</span><span class="age">{{ d.score }} {{ d.state }}</span>
        </div>
        <div class="hd mt"><b>借币红线</b><el-link type="warning" @click="$router.push('/mix/strategy/S3')">下钻 S3 →</el-link></div>
        <div class="hrow" v-for="b in borrowables" :key="b.symbol">
          <i class="dot" :class="b.health==='正常'?'ok':'bad'" /><span class="nm">{{ b.symbol }}</span><span class="age">{{ b.qty }} · {{ b.health }}</span>
        </div>

        <!-- 分策略健康（画板卡）：堵点阶段=各策略管道最大段，心跳=该层执行服务 -->
        <div class="hd mt"><b>分策略健康</b></div>
        <div class="hrow" v-for="s in stratHealth" :key="s.code">
          <span class="sdot" :style="{background:s.color}">{{ s.code }}</span>
          <span class="nm">{{ s.stage }}</span>
          <span class="age" :class="{bad2:!s.ok}">{{ s.ok ? '正常' : '停更' }}</span>
        </div>

        <!-- 公告监控（event-calendar：上市/下架事件流） -->
        <div class="hd mt"><b>公告/上市监控</b></div>
        <div class="hrow" v-for="(e, i) in events.slice(0, 6)" :key="i">
          <i class="dot warn" /><span class="nm">{{ e.type }} · {{ e.text }}</span><span class="age">{{ e.at }}</span>
        </div>
        <div v-if="!events.length" class="hrow"><i class="dot ok" /><span class="nm">近期无新上市/下架事件</span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

const watermarks = ref([]); const spreads = ref([]); const heartbeats = ref([]); const freshness = ref({}); const borrowables = ref([])
const events = ref([]); const strategies = ref([])
const SC = { S1: '#4A9CFF', S2: '#F0B90B', S3: '#A78BFA', S4: '#2DD4BF', S5: '#FF9F43', S6: '#F472B6' }
const ENGINE_SVC = { S1: 'engine-basis', S2: 'engine-dualperp', S3: 'coin-bridge', S4: 'engine-lending' }
const stratHealth = computed(() => strategies.value.map(s => {
  const pipe = s.pipeline || {}
  const numeric = Object.entries(pipe).filter(([, v]) => typeof v === 'number' && v > 0)
  const top = numeric.sort((a, b) => b[1] - a[1])[0]
  const hb = heartbeats.value.find(h => h.proc === ENGINE_SVC[s.code])
  return { code: s.code, color: SC[s.code],
           stage: s.enabled ? (top ? `堵点/主态：${top[0]} ${top[1]}` : '空闲') : (pipe['状态'] || '未启用'),
           ok: s.enabled ? (hb ? hb.ok : true) : true }
}))
const warnCount = computed(() => watermarks.value.filter(w => w.threshold !== 'ok').length)
const sign = v => String(v).startsWith('-') ? 'dn' : 'up'
const levelColor = w => w.threshold === 'withdraw' ? '#F6465D' : w.threshold === 'topup' ? '#F0B90B' : '#0ECB81'
const thLabel = w => ({ topup: '补仓线', withdraw: '提现线' }[w.threshold] || '正常')

async function load() {
  const m = mixApi.monitor
  ;[watermarks.value, spreads.value, heartbeats.value, freshness.value, borrowables.value] =
    await Promise.all([m.watermarks(), m.spreads(), m.heartbeats(), m.freshness(), m.borrowables()])
  try { events.value = await m.events(); strategies.value = await mixApi.strategies() } catch (e) { /* 降级 */ }
}
async function createOrder(w) {
  const r = await fetch(`${import.meta.env.VITE_MIX_API || 'http://localhost:8100/api/v1'}/monitor/transfer-suggestions/${w.account}/create-order`, { method: 'POST' }).then(r => r.json())
  ElMessage.success(`划转单 ${r.orderId} 已创建（${r.state}，人工确认执行）`)
}
let timer
onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped lang="scss">
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 12px; align-items: start; }
.card { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 12px 14px; font-size: 12px; display: flex; flex-direction: column; gap: 6px;
  &.gold { border-color: rgba(240,185,11,.4); } }
.hd { display: flex; align-items: center; gap: 8px; b { font-size: 13px; } .sub { color: var(--el-text-color-secondary); font-size: 10.5px; } &.mt { margin-top: 10px; } }
.wrow { display: flex; align-items: center; gap: 8px; height: 30px;
  .nm { min-width: 110px; font-weight: 700; em { font-style: normal; color: var(--el-text-color-secondary); font-size: 10px; margin-left: 4px; } }
  .amt { width: 76px; text-align: right; }
  .bar { flex: 1; height: 6px; background: var(--el-fill-color-dark); border-radius: 3px; overflow: hidden; i { display: block; height: 100%; border-radius: 3px; } }
  .th { width: 44px; font-weight: 700; font-size: 11px; } }
.ft { color: var(--el-text-color-placeholder); font-size: 10px; margin-top: 4px; }
.srow { display: grid; grid-template-columns: 76px repeat(5, 1fr) 52px; gap: 6px; align-items: center; height: 24px; text-align: right;
  &.head { color: var(--el-text-color-placeholder); font-size: 10px; border-bottom: 1px solid var(--el-border-color); }
  .sym { text-align: left; font-weight: 800; }
  .up { color: #0ECB81; } .dn { color: #F6465D; } .acc { color: #B8860B; } }
.hrow { display: flex; align-items: center; gap: 8px; height: 22px;
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--el-border-color); &.ok { background: #0ECB81; } &.warn { background: #F0B90B; } &.bad { background: #F6465D; } }
  .nm { font-weight: 600; } em { font-style: normal; color: var(--el-text-color-secondary); font-size: 10px; }
  .age { margin-left: auto; color: var(--el-text-color-secondary); } }
.sdot { display:inline-block; min-width:22px; text-align:center; font-size:9.5px; font-weight:800; color:#0B0E11; border-radius:3px; padding:0 3px; margin-right:6px; }
.bad2 { color:#F6465D; }
</style>
