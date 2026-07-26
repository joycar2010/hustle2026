<template>
  <!-- V6.2 R3+ 浮动操作引导栏(§5.1第二层):每次只展开一个最高优先级事项。
       去疲劳由服务端强制(同cue_id只auto一次/页面同时最多1个auto_expand);本组件只呈现。 -->
  <div class="grail" :class="{open: railOpen}">
    <div class="fab" @click="railOpen = !railOpen">
      <span class="ico">☰</span>
      <span v-if="badge" class="badge">{{ badge }}</span>
    </div>
    <div v-if="railOpen" class="panel">
      <div class="phd"><b>操作引导</b>
        <a class="redo" @click="$emit('retour')">重新引导</a>
        <span class="x" @click="railOpen=false">✕</span></div>
      <template v-if="top">
        <div class="cue" :class="'sev'+top.severity">
          <div class="ct"><span class="sev">{{ top.severity }}</span><b>{{ top.title }}</b></div>
          <div class="qa"><i>发生了什么</i><span>{{ top.plain_summary }}</span></div>
          <div class="qa"><i>为什么需要你</i><span>{{ top.why_now }}</span></div>
          <div class="qa"><i>你现在只需</i><span>{{ top.operator_action_text }}</span></div>
          <div class="qa"><i>完成标志</i><span>{{ top.completion_text }}</span></div>
          <div v-if="top.deadline" class="qa"><i>最晚处理</i><span>{{ String(top.deadline).slice(5,16) }}</span></div>
          <div class="acts">
            <button class="pri" @click="goPrimary(top)">去处理</button>
            <button @click="ack(top)">已知晓</button>
            <button class="ghost" @click="snooze(top)">稍后(1小时)</button>
          </div>
        </div>
        <div v-for="c in rest" :key="c.cue_id" class="mini" @click="promote(c)">
          <span class="sev">{{ c.severity }}</span>{{ c.title }}
        </div>
      </template>
      <div v-else class="empty">当前无待引导事项,自动回路按规则运行</div>
      <div class="ft">提示由服务端去重;风险级确认后状态变化会重新出现,不可永久关闭</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { mixApi } from '../../api/mix'

const emit = defineEmits(['open-item', 'retour'])
const router = useRouter()
const cues = ref([])
const railOpen = ref(false)
const pinned = ref('')
let timer = null

async function load () {
  try {
    const r = await mixApi.guidanceActive()
    cues.value = r.cues || []
    // 服务端判定 auto_expand(同cue一生只一次)→ 自动展开引导栏
    if (cues.value.some(c => c.auto_expand)) railOpen.value = true
  } catch (e) { /* 401全局接管;失败保持旧值 */ }
}
onMounted(() => { load(); timer = setInterval(load, 45000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

const top = computed(() => cues.value.find(c => c.cue_id === pinned.value) || cues.value[0] || null)
const rest = computed(() => cues.value.filter(c => c !== top.value).slice(0, 6))
const badge = computed(() => cues.value.length ? Math.min(cues.value.length, 9) : 0)

function promote (c) { pinned.value = c.cue_id }
async function ack (c) {
  try { await mixApi.guidanceAck(c.cue_id) } catch (e) {}
  cues.value = cues.value.filter(x => x.cue_id !== c.cue_id)
}
async function snooze (c) {
  try { await mixApi.guidanceSnooze(c.cue_id, 60) } catch (e) {}
  cues.value = cues.value.filter(x => x.cue_id !== c.cue_id)
}
function goPrimary (c) {
  // primary_action_ref 只允许安全深链(服务端约束);工作项 cue 直开抽屉
  if (c.scope_type === 'WORK_ITEM' && c.scope_id && c.scope_id !== 'queue') {
    emit('open-item', c.scope_id); railOpen.value = false; return
  }
  const ref = c.primary_action_ref || ''
  if (ref.startsWith('mix/')) router.push('/' + ref)
}
</script>

<style scoped>
.grail{position:fixed;right:14px;bottom:18px;z-index:1200;font-size:12px}
.fab{width:40px;height:40px;border-radius:50%;background:#181A20;border:1px solid #2B3139;color:#F0B90B;
  display:flex;align-items:center;justify-content:center;cursor:pointer;position:relative;box-shadow:0 2px 10px rgba(0,0,0,.5)}
.badge{position:absolute;top:-4px;right:-4px;background:#F6465D;color:#fff;border-radius:8px;min-width:16px;height:16px;
  display:flex;align-items:center;justify-content:center;font-size:10px;padding:0 3px}
.panel{position:absolute;right:0;bottom:48px;width:320px;background:#181A20;border:1px solid #2B3139;border-radius:6px;
  padding:10px;color:#B7BDC6;box-shadow:0 4px 24px rgba(0,0,0,.6)}
.phd{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.phd b{color:#EAECEF;flex:1}
.redo{color:#F0B90B;cursor:pointer;font-size:11px}
.x{cursor:pointer;color:#848E9C}
.cue{border:1px solid #2B3139;border-radius:5px;padding:8px;margin-bottom:6px}
.cue.sevL3,.cue.sevL4{border-color:#F6465D}
.cue.sevL2{border-color:#F0B90B}
.ct{display:flex;gap:6px;align-items:center;margin-bottom:4px}
.ct b{color:#EAECEF}
.sev{font-size:10px;padding:0 4px;border-radius:3px;background:#22262E;color:#848E9C}
.sevL3 .sev,.sevL4 .sev{background:rgba(246,70,93,.15);color:#F6465D}
.sevL2 .sev{background:rgba(240,185,11,.15);color:#F0B90B}
.qa{display:flex;gap:6px;margin:2px 0;line-height:1.5}
.qa i{color:#5E6673;font-style:normal;min-width:72px}
.qa span{flex:1;color:#B7BDC6}
.acts{display:flex;gap:6px;margin-top:6px}
.acts button{background:#22262E;border:1px solid #2B3139;color:#EAECEF;border-radius:4px;padding:3px 10px;cursor:pointer;font-size:12px}
.acts .pri{background:#F0B90B;color:#181A20;border-color:#F0B90B}
.acts .ghost{color:#848E9C}
.mini{padding:5px 8px;border:1px solid #22262E;border-radius:4px;margin-bottom:4px;cursor:pointer;display:flex;gap:6px;align-items:center}
.mini:hover{border-color:#2B3139}
.empty{color:#848E9C;padding:8px 0}
.ft{color:#5E6673;font-size:11px;margin-top:4px;line-height:1.4}
</style>
