<template>
  <v-chart :option="chartOption" :autoresize="true" class="mini-donut" />
</template>

<script setup>
import { computed } from "vue"
import VChart from "vue-echarts"
import { use } from "echarts/core"
import { PieChart } from "echarts/charts"
import { TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

use([PieChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  segments: { type: Array, default: () => [] },
  size: { type: String, default: "56px" },
})

const COLORS = ["#3b82f6", "#a855f7", "#f59e0b", "#10b981", "#ef4444", "#6366f1"]

const chartOption = computed(() => ({
  tooltip: { trigger: "item", formatter: "{b}: {d}%" },
  series: [{
    type: "pie", radius: ["55%", "85%"],
    label: { show: false }, emphasis: { scale: false },
    data: props.segments.map((s, i) => ({
      name: s.name, value: s.value,
      itemStyle: { color: s.color || COLORS[i % COLORS.length] },
    })),
    itemStyle: { borderWidth: 1, borderColor: "#1a1a2e" },
  }],
  animation: false,
}))
</script>

<style scoped>
.mini-donut { width: v-bind(size); height: v-bind(size); }
</style>
