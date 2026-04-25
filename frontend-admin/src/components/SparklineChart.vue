<template>
  <v-chart :option="chartOption" :autoresize="true" class="sparkline-chart" />
</template>

<script setup>
import { computed } from "vue"
import VChart from "vue-echarts"
import { use } from "echarts/core"
import { LineChart } from "echarts/charts"
import { GridComponent, TooltipComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
  color: { type: String, default: "#22d3ee" },
  areaColor: { type: String, default: "rgba(34,211,238,0.15)" },
  width: { type: String, default: "120px" },
  height: { type: String, default: "32px" },
  showTooltip: { type: Boolean, default: false },
})

const chartOption = computed(() => ({
  grid: { left: 0, right: 0, top: 0, bottom: 0 },
  xAxis: { type: "category", show: false, data: props.data.map((_, i) => i) },
  yAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
  tooltip: props.showTooltip ? { trigger: "axis", formatter: (p) => p[0]?.value?.toFixed(2) ?? "" } : undefined,
  series: [{
    type: "line", data: props.data, smooth: true, symbol: "none", lineStyle: { width: 1.5, color: props.color },
    areaStyle: { color: props.areaColor },
  }],
  animation: false,
}))
</script>

<style scoped>
.sparkline-chart { width: v-bind(width); height: v-bind(height); }
</style>
