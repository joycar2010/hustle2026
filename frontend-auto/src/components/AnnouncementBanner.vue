<template>
  <div v-if="maintenanceActive" class="bg-[#f6465d]/15 border-b border-[#f6465d]/40 px-3 py-1 text-center">
    <span class="text-[#f6465d] text-xs font-bold">⚠ 系统维护中{{ resumeText ? ` · ${resumeText}` : '' }}{{ reasonText ? ` — ${reasonText}` : '' }}</span>
  </div>
  <div v-else-if="annText" :class="['border-b px-3 py-1 overflow-hidden', annBg]">
    <div class="marquee-row whitespace-nowrap" :class="annTextColor">📢 {{ annText }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useWsStream } from '@/stores/wsStream.js'
import api from '@/api'

const ws = useWsStream()
ws.subscribe('site.status')
onMounted(async () => {
  try { const r = await api.get('/api/v1/site-status'); ws.channels['site.status'] = r.data } catch {}
})

const site = computed(() => ws.channels['site.status'] || { announcements: [], maintenance: {} })
const maintenanceActive = computed(() => !!site.value.maintenance?.is_active)
const reasonText = computed(() => site.value.maintenance?.reason || '')
const resumeText = computed(() => {
  const t = site.value.maintenance?.scheduled_resume_at
  if (!t) return ''
  try { return `预计 ${new Date(t).toLocaleString('zh-CN', { hour12: false })} 恢复` } catch { return '' }
})
const annText = computed(() => {
  const arr = site.value.announcements || []
  if (!arr.length) return ''
  return arr.map(a => `[${{info:'公告',warning:'警告',critical:'紧急'}[a.level]||a.level}] ${a.title}${a.content ? '：' + a.content : ''}`).join('  ·  ')
})
const annBg = computed(() => {
  const arr = site.value.announcements || []
  const has = (lv) => arr.some(a => a.level === lv)
  if (has('critical')) return 'bg-[#f6465d]/15 border-[#f6465d]/40'
  if (has('warning')) return 'bg-[#f0b90b]/15 border-[#f0b90b]/40'
  return 'bg-[#3370ff]/15 border-[#3370ff]/40'
})
const annTextColor = computed(() => {
  const arr = site.value.announcements || []
  const has = (lv) => arr.some(a => a.level === lv)
  if (has('critical')) return 'text-[#f6465d] text-xs font-semibold'
  if (has('warning')) return 'text-[#f0b90b] text-xs font-semibold'
  return 'text-[#3370ff] text-xs font-semibold'
})

defineExpose({ maintenanceActive })
</script>

<style scoped>
.marquee-row {
  display: inline-block;
  animation: marquee 25s linear infinite;
}
@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-100%); }
}
</style>
