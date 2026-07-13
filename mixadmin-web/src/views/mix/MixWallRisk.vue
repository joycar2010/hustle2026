<template>
  <div class="wall" v-if="ok">
    <div class="hd">
      <b>HustleCoin Mix · 多屏指挥墙</b><span class="pos">屏 3 / 3 · 风控指挥</span>
      <span class="clk">{{ clock }}</span>
    </div>

    <!-- 第一排：支撑域A(AI 决策) / 风控护栏 / 系统健康 -->
    <div class="toprow">
      <div class="card gold">
        <div class="chd">支撑域 A · AI 决策 <span class="sub">分域顾问制 · 可整体摘除</span></div>
        <div v-for="a in ov.advisors || []" :key="a.name" class="adv">
          <i class="dot" :class="{bad: a.status==='停更'}"></i>
          <b class="anm">{{ a.name }}</b><span class="acad">{{ a.cadence }}</span>
          <em class="ast" :class="{off: a.status==='停更'}">{{ a.status }}</em>
        </div>
        <div class="adv dim">
          <i class="dot off"></i><b class="anm">折价分诊分析师</b><span class="acad">事件触发</span><em class="ast off">S5 未启用</em>
        </div>
        <div class="adv dim">
          <i class="dot off"></i><b class="anm">全局配置器</b><span class="acad">周级·资金权重</span><em class="ast off">未启用</em>
        </div>
        <div class="gov">
          <span class="gstep">schema 强制</span><i>→</i><span class="gstep">硬校验钳位</span><i>→</i>
          <span class="gstep">快照回滚</span><i>→</i><span class="gstep">shadow 对照跑赢才 enforce</span>
        </div>
        <div class="gnote">摘除 AI 层 = 只持有不新增 · 只告警不动手</div>
      </div>

      <div class="card">
        <div class="chd">支撑域 B · 风控护栏</div>
        <div class="kv"><span>实盘总权益</span><b>{{ num(ov.risk?.total_equity) }} U</b></div>
        <div class="kv"><span>跨域净敞口越线</span><b :class="ov.risk?.net_breaches ? 'down' : 'up'">{{ ov.risk?.net_breaches ?? '—' }}（地板 {{ ov.risk?.net_floor ?? '—' }}U）</b></div>
        <div class="kv"><span>孤儿实盘仓（RECON）</span><b :class="ov.risk?.orphans ? 'down' : 'up'">{{ ov.risk?.orphans ?? '—' }}</b></div>
        <div class="kv"><span>最高有效杠杆</span><b>{{ ov.risk?.max_lev ?? '—' }}x</b></div>
        <div class="kv"><span>本轮告警</span><b :class="ov.risk?.alerts_this_round ? 'warn' : 'up'">{{ ov.risk?.alerts_this_round ?? '—' }}</b></div>
        <div class="kv"><span>当日净收益（落袋）</span><b :class="(ov.pnl_today||0) >= 0 ? 'up' : 'down'">{{ num(ov.pnl_today) }} U</b></div>
        <div class="bgrid">
          <span v-for="g in ov.support_b || []" :key="g.name" class="svc">
            <i class="dot" :class="{bad: !g.ok}"></i>{{ g.name }}
          </span>
        </div>
      </div>

      <div class="card">
        <div class="chd">系统健康 <b class="up">{{ ov.health?.ok ?? '—' }}/{{ ov.health?.total ?? '—' }}</b></div>
        <div class="svc-grid">
          <span v-for="(st, name) in ov.health?.services || {}" :key="name" class="svc">
            <i class="dot" :class="{bad: st !== 'ok'}"></i>{{ name }}
          </span>
        </div>
        <div class="chd" style="margin-top:10px">进程心跳 <span class="sub">dcm:hb:* 真相源</span></div>
        <div class="hb-grid">
          <span v-for="h in heartbeats.slice(0,12)" :key="h.proc" class="svc">
            <i class="dot" :class="{bad: !h.ok}"></i>{{ h.proc }} <em>{{ h.age }}</em>
          </span>
        </div>
      </div>
    </div>

    <!-- 第二排：变更审计（规则/干预/AI 决策留痕,自规则中心迁入） -->
    <div class="card">
      <div class="chd">变更审计 <span class="sub">admin_audit 全量留痕 · S3 借币点差 规则模板变更 + 干预 + AI 配置</span></div>
      <div class="audit3">
        <div v-for="(a,i) in audit" :key="i" class="arec">
          <span class="at">{{ a.at }}</span><b class="au">{{ a.user }}</b>
          <span class="af">{{ a.field }}</span><em class="ac" :title="a.change">{{ a.change }}</em>
        </div>
        <div v-if="!audit.length" class="arec"><span style="color:#5E6673">暂无变更记录</span></div>
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
const ov = ref({}); const heartbeats = ref([]); const alerts = ref([]); const audit = ref([])
const clock = ref('')
const num = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }))

async function load() {
  try {
    ;[ov.value, heartbeats.value, alerts.value] =
      await Promise.all([mixApi.monitor.overview(), mixApi.monitor.heartbeats(), mixApi.alerts()])
    ok.value = true
    try { audit.value = (await mixApi.rulesAudit('strategy:S3')).slice(0, 24) } catch (e) { /* 降级 */ }
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
.card.gold { border-color: rgba(240,185,11,.35); }
.adv { display: flex; align-items: center; gap: 8px; font-size: 11.5px; padding: 3.5px 0;
  &.dim { opacity: .55; }
  .anm { color: #EAECEF; min-width: 108px; }
  .acad { flex: 1; color: #5E6673; font-size: 10px; }
  .ast { font-style: normal; color: #0ECB81; font-weight: 700; font-size: 10.5px; &.off { color: #5E6673; font-weight: 400; } } }
.dot.off { background: #5E6673; }
.gov { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #262B33;
  .gstep { background: rgba(240,185,11,.1); border: 1px solid rgba(240,185,11,.3); color: #F0B90B;
    border-radius: 10px; padding: 1px 8px; font-size: 9.5px; font-weight: 700; }
  i { color: #5E6673; font-style: normal; font-size: 10px; } }
.gnote { margin-top: 6px; font-size: 10px; color: #5E6673; }
.bgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 3px 10px; margin-top: 10px; padding-top: 8px; border-top: 1px dashed #262B33; }
.audit3 { column-count: 3; column-gap: 16px; }
.arec { break-inside: avoid; display: flex; align-items: baseline; gap: 6px; font-size: 11px; padding: 2.5px 0;
  .at { color: #5E6673; flex: none; } .au { color: #F0B90B; flex: none; }
  .af { color: #EAECEF; flex: none; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ac { font-style: normal; color: #848E9C; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.gate { min-height: 100vh; background: #0B0E11; color: #848E9C; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;
  b { color: #EAECEF; font-size: 18px; } }
</style>
