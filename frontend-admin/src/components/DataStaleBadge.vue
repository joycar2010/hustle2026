<template>
  <span v-if="isStale" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-yellow-900/40 text-yellow-400 animate-pulse">
    <span class="w-1.5 h-1.5 rounded-full bg-yellow-400"></span>
    数据延迟 {{ ageSec }}s
  </span>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from "vue"

const props = defineProps({
  lastUpdateAt: { type: Number, default: 0 },
  thresholdMs: { type: Number, default: 30000 },
})

const now = ref(Date.now())
let timer = setInterval(() => { now.value = Date.now() }, 2000)
onUnmounted(() => clearInterval(timer))

const isStale = computed(() => props.lastUpdateAt > 0 && (now.value - props.lastUpdateAt) > props.thresholdMs)
const ageSec = computed(() => Math.floor((now.value - props.lastUpdateAt) / 1000))
</script>
