<template>
  <div class="wall">
    <div v-if="!authed" class="gate">屏 3 / 3 · 风控指挥与资金<br /><small>URL 需携带 ?token=（只读墙令牌，后端校验）</small></div>
    <template v-else>
      <div class="bar">
        <b>HustleCoin Mix · 多屏指挥墙</b><span class="pos">屏 3 / 3 · 风控指挥与资金</span>
        <span class="right">数据 5s 自刷新 · {{ clock }}</span>
      </div>
      <div class="grid">
        <div class="card">
          <div class="hd">账户余额水位</div>
          <div v-for="w in watermarks" :key="w.account" class="wrow">
            <b>{{ w.account }}</b><em>{{ w.venue }}</em><span>{{ w.available }}</span>
            <span class="bar2"><i :style="{ width:(w.level*100)+'%', background: w.threshold==='withdraw'?'#F6465D':w.threshold==='topup'?'#F0B90B':'#0ECB81' }" /></span>
            <span class="sug">{{ w.suggestion?.text || '—' }}</span>
          </div>
        </div>
        <div class="card">
          <div class="hd">实时告警流水</div>
          <div v-for="(a,i) in alerts" :key="i" class="arow">
            <em>{{ a.at }}</em><i class="lv" :class="a.level">{{ a.level }}</i>
            <i class="sc">{{ a.strategy }}</i><span>{{ a.text }}</span>
          </div>
          <div class="hd mt">进程心跳</div>
          <div v-for="h in heartbeats" :key="h.proc+h.shard" class="arow">
            <i class="dot" :class="{ok:h.ok}" /><span>{{ h.proc }} · {{ h.shard }}</span><em class="ml">{{ h.age }}</em>
          </div>
        </div>
        <div class="card">
          <div class="hd">支撑域 A · AI 决策（分域顾问制）<i class="tag">可整体摘除</i></div>
          <div v-for="a in advisors" :key="a[0]" class="arow">
            <span class="nm">{{ a[0] }}</span><em>{{ a[1] }}</em><i class="st" :class="a[3]">{{ a[2] }}</i>
          </div>
          <div class="note">schema 结构化 → 硬校验钳位 → 快照回滚 → shadow 跑赢才 enforce；摘除后=只持有不新增、只告警不动手</div>
          <div class="hd mt">支撑域 B · 风控与运营 <b class="ok10">10/10</b></div>
          <div class="opsgrid">
            <span v-for="o in opsItems" :key="o"><i class="dot ok" />{{ o }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { mixApi } from '../../api/mix'

const route = useRoute()
const authed = ref(!!route.query.token)
const watermarks = ref([]); const alerts = ref([]); const heartbeats = ref([])
const clock = ref('')
const advisors = [
  ['carry 组合顾问', '小时级 · 跨引擎选对/基差择时/退出体制', 'enforce · +2.1% 跑赢', 'ok'],
  ['借贷增强顾问', '小时级 · 利差撮合与期限', 'shadow 对照中', 'warn'],
  ['折价分诊分析师', '事件触发 · LST/锚定折价', '待事件', 'idle'],
  ['全局配置器', '周级 · 资金权重再平衡', '下次 07-14', 'idle'],
]
const opsItems = ['跨域净敞口账本·自动收敛','RECON 双腿配对对账','单腿 / ADL 告警','裸空安全网 0.5s 巡检','还币闸','飞书双轨告警·令牌桶','PnL 三表持久化核算','净值 / 归因面板','AI 审计四件套','双域隔离·多用户权限']

async function load() {
  ;[watermarks.value, alerts.value, heartbeats.value] =
    await Promise.all([mixApi.monitor.watermarks(), mixApi.alerts(), mixApi.monitor.heartbeats()])
}
let t1, t2
onMounted(() => { if (authed.value) { load(); t1 = setInterval(load, 5000) } t2 = setInterval(() => clock.value = new Date().toLocaleTimeString('zh-CN'), 1000) })
onUnmounted(() => { clearInterval(t1); clearInterval(t2) })
</script>

<style scoped lang="scss">
.wall { min-height: 100vh; background: #0B0E11; color: #EAECEF; padding: 14px 20px; font-size: 12px; }
.gate { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 80vh; gap: 8px; color: #848E9C; font-size: 18px; text-align: center; }
.bar { display: flex; gap: 12px; align-items: center; padding-bottom: 10px; border-bottom: 1px solid #262B33; margin-bottom: 12px;
  b { font-size: 14px; } .pos { background: rgba(240,185,11,.14); color: #F0B90B; border-radius: 5px; padding: 2px 10px; font-weight: 700; }
  .right { margin-left: auto; color: #5E6673; } }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 12px; align-items: start; }
.card { background: #181B21; border: 1px solid #262B33; border-radius: 10px; padding: 12px 14px; }
.hd { font-weight: 700; font-size: 13px; margin-bottom: 8px; &.mt { margin-top: 12px; }
  .tag { font-style: normal; font-size: 9px; color: #4A9CFF; border: 1px solid rgba(74,156,255,.4); border-radius: 4px; padding: 1px 6px; margin-left: 8px; }
  .ok10 { color: #0ECB81; } }
.wrow { display: flex; gap: 8px; align-items: center; height: 30px;
  b { min-width: 92px; } em { font-style: normal; color: #5E6673; min-width: 46px; }
  .bar2 { flex: 1; height: 6px; background: #20242C; border-radius: 3px; overflow: hidden; i { display: block; height: 100%; } }
  .sug { color: #848E9C; font-size: 10px; max-width: 160px; } }
.arow { display: flex; gap: 8px; align-items: center; height: 26px;
  em { font-style: normal; color: #5E6673; font-size: 10px; } .ml { margin-left: auto; }
  .nm { min-width: 108px; font-weight: 700; }
  .lv { font-style: normal; border-radius: 3px; padding: 1px 6px; font-size: 9px; font-weight: 800;
    &.FATAL { background: rgba(246,70,93,.2); color: #F6465D; } &.WARN { background: rgba(240,185,11,.2); color: #F0B90B; } &.INFO { background: rgba(74,156,255,.2); color: #4A9CFF; } }
  .sc { font-style: normal; color: #F0B90B; font-size: 10px; font-weight: 800; }
  .st { font-style: normal; margin-left: auto; border-radius: 3px; padding: 1px 7px; font-size: 9px; font-weight: 700;
    &.ok { background: rgba(14,203,129,.15); color: #0ECB81; } &.warn { background: rgba(240,185,11,.15); color: #F0B90B; } &.idle { background: rgba(132,142,156,.15); color: #848E9C; } } }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #262B33; &.ok { background: #0ECB81; } }
.note { color: #5E6673; font-size: 10px; margin-top: 4px; }
.opsgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px;
  span { display: inline-flex; gap: 6px; align-items: center; color: #848E9C; font-size: 11px; } }
</style>
