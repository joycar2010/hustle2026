<template>
  <div class="wall" v-if="ok">
    <div class="hd">
      <b>HustleCoin Mix · 多屏指挥墙</b><span class="pos">屏 3 / 3 · 风控指挥</span>
      <span class="clk">{{ clock }}</span>
    </div>

    <div class="toprow">
      <div class="card">
        <div class="chd">系统健康 <b class="up">{{ ov.health?.ok ?? '—' }}/{{ ov.health?.total ?? '—' }}</b></div>
        <div class="svc-grid">
          <span v-for="(st, name) in ov.health?.services || {}" :key="name" class="svc">
            <i class="dot" :class="{bad: st !== 'ok'}"></i>{{ name }}
          </span>
        </div>
      </div>

      <div class="card">
        <div class="chd">风控护栏</div>
        <div class="kv"><span>实盘总权益</span><b>{{ num(ov.risk?.total_equity) }} U</b></div>
        <div class="kv"><span>净敞口越线</span><b :class="ov.risk?.net_breaches ? 'down' : 'up'">{{ ov.risk?.net_breaches ?? '—' }}（地板 {{ ov.risk?.net_floor ?? '—' }}U）</b></div>
        <div class="kv"><span>孤儿实盘仓</span><b :class="ov.risk?.orphans ? 'down' : 'up'">{{ ov.risk?.orphans ?? '—' }}</b></div>
        <div class="kv"><span>最高有效杠杆</span><b>{{ ov.risk?.max_lev ?? '—' }}x</b></div>
        <div class="kv"><span>本轮告警</span><b :class="ov.risk?.alerts_this_round ? 'warn' : 'up'">{{ ov.risk?.alerts_this_round ?? '—' }}</b></div>
        <div class="kv"><span>当日净收益</span><b :class="(ov.pnl_today||0) >= 0 ? 'up' : 'down'">{{ num(ov.pnl_today) }} U</b></div>
      </div>

      <div class="card">
        <div class="chd">进程心跳 <span class="sub">dcm:hb:* 真相源</span></div>
        <div class="hb-grid">
          <span v-for="h in heartbeats" :key="h.proc" class="svc">
            <i class="dot" :class="{bad: !h.ok}"></i>{{ h.proc }} <em>{{ h.age }}</em>
          </span>
        </div>
      </div>
    </div>

    <!-- 实时告警流水 · 底部三列 -->
    <div class="chd alerts-hd">实时告警流水（最近 {{ alerts.length }} 条）</div>
    <div class="alerts3">
      <div v-for="(a, i) in alerts.slice(0, 30)" :key="i" class="arow">
        <span class="lv" :class="a.level.toLowerCase()">{{ a.level }}</span>
        <span v-if="a.strategy" class="sb" :style="{background: SC[a.strategy]}">{{ a.strategy }}</span>
        <span class="at">{{ a.at }}</span>
        <span class="tx" :title="a.text">{{ a.text }}</span>
      </div>
    </div>
  </div>
  <div class="gate" v-else>
    <b>屏 3 · 风控墙</b>
    <p>需要墙令牌：/wall/risk?token=…</p>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { mixApi } from '../../api/mix'

const SC = { S1: '#4A9CFF', S2: '#F0B90B', S3: '#A78BFA', S4: '#2DD4BF', S5: '#FF9F43', S6: '#F472B6' }
const route = useRoute()
const ok = ref(false)
const ov = ref({}); const heartbeats = ref([]); const alerts = ref([])
const clock = ref('')
const num = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))

async function load() {
  try {
    ;[ov.value, heartbeats.value, alerts.value] =
      await Promise.all([mixApi.monitor.overview(), mixApi.monitor.heartbeats(), mixApi.alerts()])
    ok.value = true
  } catch (e) { ok.value = !!ov.value?.health }
}
let t1, t2
onMounted(() => {
  const qt = route.query.token
  if (qt) localStorage.setItem('mix_token', String(qt))   // 墙令牌引导（同源 API 头）
  load()
  t1 = setInterval(load, 5000)
  t2 = setInterval(() => { clock.value = new Date().toTimeString().slice(0, 8) }, 1000)
})
onUnmounted(() => { clearInterval(t1); clearInterval(t2) })
</script>

<style scoped lang="scss">
.wall { min-height: 100vh; background: #0B0E11; color: #EAECEF; padding: 18px 22px; display: flex; flex-direction: column; gap: 12px; }
.hd { display: flex; align-items: baseline; gap: 12px; b { font-size: 18px; } .pos { color: #848E9C; font-size: 12px; flex: 1; } .clk { font-size: 14px; color: #F0B90B; } }
.toprow { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
.card { background: #181B21; border: 1px solid #262B33; border-radius: 10px; padding: 12px 14px; }
.chd { font-size: 13px; font-weight: 700; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;
  .sub { color: #5E6673; font-size: 10.5px; font-weight: 400; } }
.svc-grid, .hb-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; }
.svc { font-size: 11px; color: #848E9C; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  em { font-style: normal; color: #5E6673; margin-left: 4px; } }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #0ECB81; margin-right: 6px;
  &.bad { background: #F6465D; } }
.kv { display: flex; justify-content: space-between; font-size: 12px; color: #848E9C; padding: 3px 0; b { color: #EAECEF; } }
.alerts-hd { margin-top: 2px; }
.alerts3 { column-count: 3; column-gap: 14px; }
.arow { break-inside: avoid; display: flex; align-items: center; gap: 6px; font-size: 11.5px; padding: 3px 0; }
.lv { font-size: 9.5px; font-weight: 700; border-radius: 3px; padding: 0 4px;
  &.fatal { background: rgba(246,70,93,.18); color: #F6465D; }
  &.warn { background: rgba(240,185,11,.15); color: #F0B90B; }
  &.info { background: rgba(74,156,255,.15); color: #4A9CFF; } }
.sb { font-size: 9.5px; font-weight: 800; color: #0B0E11; border-radius: 3px; padding: 0 4px; }
.at { color: #5E6673; }
.tx { flex: 1; color: #848E9C; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.up { color: #0ECB81; } .down { color: #F6465D; } .warn { color: #F0B90B; }
.gate { min-height: 100vh; background: #0B0E11; color: #848E9C; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  b { color: #EAECEF; font-size: 18px; } }
</style>
