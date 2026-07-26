<template>
  <!-- V6.2 R3+ 首次聚光引导(§5.1第三层):指向真实控件;同课程版本完成后不再自动出现。
       支持 prefers-reduced-motion(无动画只定位);ESC/跳过随时退出。 -->
  <teleport to="body">
    <div v-if="active && rect" class="cmwrap" @keydown.esc="finish(false)" tabindex="-1" ref="wrap">
      <div class="spot" :style="spotStyle"></div>
      <div class="tip" :style="tipStyle">
        <div class="st">{{ stepIdx+1 }}/{{ steps.length }} · <b>{{ step.title }}</b></div>
        <p>{{ step.text }}</p>
        <div class="acts">
          <button v-if="stepIdx>0" class="ghost" @click="stepIdx--">上一步</button>
          <button class="pri" @click="next">{{ stepIdx===steps.length-1 ? '完成' : '下一步' }}</button>
          <button class="ghost" @click="finish(false)">跳过</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },   // [{selector,title,text}]
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'done'])

const active = computed({ get: () => props.modelValue, set: v => emit('update:modelValue', v) })
const stepIdx = ref(0)
const rect = ref(null)
const wrap = ref(null)
const step = computed(() => props.steps[stepIdx.value] || {})

function locate () {
  rect.value = null
  const s = props.steps[stepIdx.value]
  if (!s) return
  const el = document.querySelector(s.selector)
  if (!el) { // 控件不在(视图切换等):跳过该步,不硬指空气
    if (stepIdx.value < props.steps.length - 1) { stepIdx.value++; return }
    finish(true); return
  }
  el.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  const r = el.getBoundingClientRect()
  rect.value = { x: r.left - 6, y: r.top - 6, w: r.width + 12, h: r.height + 12 }
}
watch([() => props.modelValue, stepIdx], async () => {
  if (!props.modelValue) return
  await nextTick(); setTimeout(locate, 120)
  setTimeout(() => wrap.value?.focus?.(), 200)
}, { immediate: true })

let onResize = () => locate()
window.addEventListener('resize', onResize)
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

function next () { stepIdx.value === props.steps.length - 1 ? finish(true) : stepIdx.value++ }
function finish (completed) {
  active.value = false
  emit('done', completed)   // completed=true 才记课程进度;跳过不算完成(§10:不以点过按钮判定)
  stepIdx.value = 0
}

const spotStyle = computed(() => rect.value ? {
  left: rect.value.x + 'px', top: rect.value.y + 'px',
  width: rect.value.w + 'px', height: rect.value.h + 'px',
} : {})
const tipStyle = computed(() => {
  if (!rect.value) return {}
  const below = rect.value.y + rect.value.h + 150 < window.innerHeight
  return {
    left: Math.min(Math.max(12, rect.value.x), window.innerWidth - 330) + 'px',
    top: (below ? rect.value.y + rect.value.h + 10 : Math.max(12, rect.value.y - 150)) + 'px',
  }
})
</script>

<style scoped>
.cmwrap{position:fixed;inset:0;z-index:2000;outline:none}
.spot{position:fixed;border:2px solid #F0B90B;border-radius:6px;
  box-shadow:0 0 0 9999px rgba(0,0,0,.62);pointer-events:none;transition:all .18s ease}
@media (prefers-reduced-motion: reduce){.spot{transition:none}}
.tip{position:fixed;width:318px;background:#181A20;border:1px solid #2B3139;border-radius:6px;
  padding:10px 12px;color:#B7BDC6;font-size:12px;box-shadow:0 4px 24px rgba(0,0,0,.6)}
.st{color:#848E9C;margin-bottom:4px}
.st b{color:#EAECEF}
.tip p{margin:0 0 8px;line-height:1.6;color:#EAECEF}
.acts{display:flex;gap:6px}
.acts button{background:#22262E;border:1px solid #2B3139;color:#EAECEF;border-radius:4px;padding:3px 12px;cursor:pointer;font-size:12px}
.acts .pri{background:#F0B90B;color:#181A20;border-color:#F0B90B}
.acts .ghost{color:#848E9C}
</style>
