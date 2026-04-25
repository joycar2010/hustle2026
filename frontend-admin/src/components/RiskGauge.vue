<template>
  <v-chart :option="chartOption" :autoresize="true" class="risk-gauge" />
</template>

<script setup>
import { computed } from "vue"
import VChart from "vue-echarts"
import { use } from "echarts/core"
import { GaugeChart } from "echarts/charts"
import { CanvasRenderer } from "echarts/renderers"

use([GaugeChart, CanvasRenderer])

const props = defineProps({
  value: { type: Number, default: 0 },
  width: { type: String, default: "100px" },
  height: { type: String, default: "60px" },
})

const chartOption = computed(() => ({
  series: [{
    type: "gauge", startAngle: 180, endAngle: 0,
    center: ["50%", "85%"], radius: "110%",
    min: 0, max: 100,
    axisLine: {
      lineStyle: {
        width: 8,
        color: [[0.3, "#22c55e"], [0.6, "#eab308"], [0.8, "#f97316"], [1, "#ef4444"]],
      },
    },
    axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
    pointer: { length: "60%", width: 3, itemStyle: { color: "#e2e8f0" } },
    detail: {
      valueAnimation: true, formatter: "{value}%",
      fontSize: 11, fontWeight: "bold", color: "#e2e8f0",
      offsetCenter: [0, "-15%"],
    },
    data: [{ value: props.value }],
  }],
  animation: false,
}))
</script>

<style scoped>
.risk-gauge { width: v-bind(width); height: v-bind(height); }
</style>
