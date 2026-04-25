<template>
  <div class="flex items-center gap-2 text-xs">
    <div class="text-right flex-1">
      <div class="text-text-tertiary mb-0.5">{{ labelA }}</div>
      <div class="font-mono font-bold" :class="valueA > 0 ? 'text-blue-400' : 'text-text-tertiary'">{{ fmtLots(valueA) }}</div>
    </div>
    <div class="relative flex-shrink-0" style="width:80px;height:28px">
      <div class="absolute inset-0 flex items-center">
        <div class="h-0.5 w-full bg-border-secondary rounded"></div>
      </div>
      <div class="absolute top-0 left-1/2 -translate-x-1/2 w-0 h-0 border-l-[6px] border-r-[6px] border-b-[8px] border-transparent transition-transform duration-300"
        :style="pivotStyle" :class="balanced ? 'border-b-green-500' : 'border-b-red-500'"></div>
      <div class="absolute bottom-0 left-0 h-1.5 rounded-full transition-all duration-300 bg-blue-500/60" :style="{ width: barA + '%' }"></div>
      <div class="absolute bottom-0 right-0 h-1.5 rounded-full transition-all duration-300 bg-purple-500/60" :style="{ width: barB + '%' }"></div>
    </div>
    <div class="flex-1">
      <div class="text-text-tertiary mb-0.5">{{ labelB }}</div>
      <div class="font-mono font-bold" :class="valueB > 0 ? 'text-purple-400' : 'text-text-tertiary'">{{ fmtLots(valueB) }}</div>
    </div>
    <div class="flex-shrink-0 w-8 text-center">
      <span v-if="balanced" class="text-green-400 text-[10px]">&#10003;</span>
      <span v-else class="text-red-400 text-[10px] font-bold">{{ deviationPct }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
  valueA: { type: Number, default: 0 },
  valueB: { type: Number, default: 0 },
  labelA: { type: String, default: "CEX" },
  labelB: { type: String, default: "MT5" },
  threshold: { type: Number, default: 0.05 },
})

function fmtLots(v) { return v != null ? Math.abs(v).toFixed(2) : "--" }

const total = computed(() => Math.abs(props.valueA) + Math.abs(props.valueB) || 1)
const barA = computed(() => (Math.abs(props.valueA) / total.value * 50).toFixed(1))
const barB = computed(() => (Math.abs(props.valueB) / total.value * 50).toFixed(1))
const deviation = computed(() => total.value > 0 ? Math.abs(Math.abs(props.valueA) - Math.abs(props.valueB)) / total.value : 0)
const balanced = computed(() => deviation.value <= props.threshold)
const deviationPct = computed(() => (deviation.value * 100).toFixed(0) + "%")
const pivotStyle = computed(() => {
  const tilt = (Math.abs(props.valueA) - Math.abs(props.valueB)) / total.value * 20
  return { transform: `translateX(-50%) rotate(${tilt}deg)` }
})
</script>
