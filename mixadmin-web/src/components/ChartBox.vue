<template>
  <div ref="el" :style="{width:'100%',height:height+'px'}"></div>
</template>
<script setup>
// 轻量 echarts 包裹:传 option 即渲染,自适应容器尺寸,组件卸载清理。
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ option:{type:Object,required:true}, height:{type:Number,default:260} })
const el = ref(null)
let chart = null, ro = null
function render(){ if(!chart||!props.option) return; chart.setOption(props.option, true) }
onMounted(()=>{
  chart = echarts.init(el.value)
  render()
  ro = new ResizeObserver(()=>{ chart && chart.resize() })
  ro.observe(el.value)
})
watch(()=>props.option, render, { deep:true })
onBeforeUnmount(()=>{ ro&&ro.disconnect(); chart&&chart.dispose(); chart=null })
</script>
