<template>
  <v-chart :option="chartOption" :autoresize="true" class="mini-bar" />
</template>

<script setup>
import { computed } from "vue"
import VChart from "vue-echarts"
import { use } from "echarts/core"
import { BarChart } from "echarts/charts"
import { GridComponent } from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

use([BarChart, GridComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
  labels: { type: Array, default: () => [] },
  highlightLast: { type: Boolean, default: true },
  width: { type: String, default: "120px" },
  height: { type: String, default: "40px" },
})

const chartOption = computed(() => ({
  grid: { left: 0, right: 0, top: 2, bottom: 0 },
  xAxis: { type: "category", show: false, data: props.labels.length ? props.labels : props.data.map((_, i) => i) },
  yAxis: { type: "value", show: false },
  series: [{
    type: "bar", data: props.data.map((v, i) => ({
      value: v,
      itemStyle: {
        color: v >= 0 ? (props.highlightLast && i === props.data.length - 1 ? "#22c55e" : "rgba(34,197,94,0.4)") : (props.highlightLast && i === props.data.length - 1 ? "#ef4444" : "rgba(239,68,68,0.4)"),
        borderRadius: [2, 2, 0, 0],
      },
    })),
    barWidth: "60%",
  }],
  animation: false,
}))
</script>

<style scoped>
.mini-bar { width: v-bind(width); height: v-bind(height); }
</style>
