<template>
  <div class="wall">
    <div v-if="!authed" class="gate">屏 1 / 3 · 机会捕捉与聚合行情<br /><small>URL 需携带 ?token=（只读墙令牌，后端校验）</small></div>
    <template v-else>
      <div class="bar">
        <b>HustleCoin Mix · 多屏指挥墙</b><span class="pos">屏 1 / 3 · 机会捕捉与聚合行情</span>
        <span class="right">数据 5s 自刷新 · {{ clock }}</span>
      </div>
      <div class="grid">
        <div class="card">
          <div class="hd">策略管道总览</div>
          <div v-for="s in strategies" :key="s.code" class="prow">
            <b class="code">{{ s.code }}</b><span class="nm">{{ s.name }}</span>
            <span class="pipe"><i v-for="(v,k) in s.pipeline" :key="k"><em>{{ k }}</em><b>{{ v }}</b></i></span>
          </div>
        </div>
        <div class="card">
          <div class="hd">币种利差 <small>开/平点差 · 净利差 · 可开状态</small></div>
          <div v-for="s in spreads" :key="s.symbol" class="srow">
            <b>{{ s.symbol }}</b>
            <span :class="sign(s.open)">{{ s.open }}</span><span :class="sign(s.close)">{{ s.close }}</span>
            <span class="acc">{{ s.dailyRate }}</span><b :class="sign(s.net)">{{ s.net }}</b>
            <i class="st" :class="s.status">{{ s.status }}</i>
          </div>
        </div>
        <div class="card">
          <div class="hd">借币可借（S3 进料口）</div>
          <div v-for="b in borrowables" :key="b.symbol" class="srow">
            <b>{{ b.symbol }}</b><span>{{ b.qty }}</span><span>{{ b.usd }}</span>
            <i class="st" :class="b.health==='正常'?'可开':'不可'">{{ b.health }}</i>
          </div>
          <div class="hd" style="margin-top:10px">公告 / 新上市（event-calendar）</div>
          <div v-for="(e, i) in events.slice(0, 8)" :key="i" class="srow">
            <b>{{ e.type }}</b><span>{{ e.text }}</span><span>{{ e.at }}</span>
          </div>
          <div v-if="!events.length" class="srow"><span style="color:#5E6673">近期无新上市/下架事件</span></div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
const events = ref([])
import { mixApi } from '../../api/mix'

const route = useRoute()
const authed = ref(!!route.query.token)
if (route.query.token) localStorage.setItem('mix_token', String(route.query.token))  // 墙令牌引导同源 API 头   // mock 门槛；真实实现由后端校验只读墙令牌
const strategies = ref([]); const spreads = ref([]); const borrowables = ref([])
const clock = ref('')
const sign = v => String(v).startsWith('-') ? 'dn' : 'up'
async function load() {
  ;[strategies.value, spreads.value, borrowables.value] =
    await Promise.all([mixApi.strategies(), mixApi.monitor.spreads(), mixApi.monitor.borrowables()])
  try { events.value = await mixApi.monitor.events() } catch (e) { /* 降级 */ }
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
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 12px; }
.card { background: #181B21; border: 1px solid #262B33; border-radius: 10px; padding: 12px 14px; }
.hd { font-weight: 700; font-size: 13px; margin-bottom: 8px; small { color: #5E6673; font-weight: 400; margin-left: 8px; } }
.prow { display: flex; gap: 10px; align-items: center; height: 30px;
  .code { color: #F0B90B; } .nm { width: 110px; color: #848E9C; }
  .pipe { display: flex; gap: 8px; overflow: hidden;
    i { font-style: normal; background: #12151A; border-radius: 4px; padding: 2px 7px; display: inline-flex; gap: 4px;
      em { font-style: normal; color: #5E6673; font-size: 9px; } b { font-size: 11px; } } } }
.srow { display: grid; grid-template-columns: 90px 1fr 1fr 1fr 60px 44px; gap: 6px; align-items: center; height: 24px; text-align: right;
  b:first-child { text-align: left; }
  .up { color: #0ECB81; } .dn { color: #F6465D; } .acc { color: #F0B90B; }
  .st { font-style: normal; border-radius: 3px; padding: 1px 6px; font-size: 9px; font-weight: 700; text-align: center;
    &.可开 { background: rgba(14,203,129,.15); color: #0ECB81; }
    &.观察 { background: rgba(132,142,156,.15); color: #848E9C; }
    &.不可 { background: rgba(246,70,93,.15); color: #F6465D; } } }
</style>
