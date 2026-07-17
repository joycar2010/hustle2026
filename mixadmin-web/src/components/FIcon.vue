<template>
  <!-- 扁平功能图标(去 emoji):stroke=currentColor,随所在处文字色/主色自适应(需求#4)。
       用法 <FIcon name="check" :size="14"/>;色由父级 color 决定,不自带颜色。 -->
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       :stroke-width="sw" stroke-linecap="round" stroke-linejoin="round" class="fic" aria-hidden="true">
    <path v-for="(d,i) in paths" :key="i" :d="d"/>
    <circle v-for="(c,i) in circles" :key="'c'+i" :cx="c[0]" :cy="c[1]" :r="c[2]"/>
  </svg>
</template>
<script setup>
import { computed } from 'vue'
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 14 },
  sw: { type: [Number, String], default: 2 },
})
// 语义名 → SVG 几何(lucide 风格 24 网格)。circles 单列,paths 主体。
const P = {
  check: ['M20 6 9 17l-5-5'],
  x: ['M18 6 6 18M6 6l12 12'],
  warn: ['M12 3 2 20h20L12 3Z', 'M12 10v4', 'M12 17.5v.5'],
  alert: ['M12 8v5', 'M12 16.5v.5', 'M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z'],
  shield: ['M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3Z'],
  pause: ['M8 5v14M16 5v14'],
  gear: ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z', 'M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.4 1a7 7 0 0 0-1.7-1l-.3-2.5h-4l-.3 2.5a7 7 0 0 0-1.7 1l-2.4-1-2 3.5 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7 7 0 0 0 1.7 1l.3 2.5h4l.3-2.5a7 7 0 0 0 1.7-1l2.4 1 2-3.5-2-1.5c.1-.3.1-.7.1-1Z'],
  tool: ['M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2-2 2.5-2.5Z'],
  lock: ['M5 11h14v10H5V11Z', 'M8 11V7a4 4 0 0 1 8 0v4'],
  key: ['M15 9a3 3 0 1 0-3 3M12 12l-7 7v2h2l1-1h2v-2h2l2-2'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M4 21a8 8 0 0 1 16 0'],
  eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z', 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z'],
  bell: ['M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9', 'M13.7 21a2 2 0 0 1-3.4 0'],
  chat: ['M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z'],
  star: ['M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.5 6.8 19.2l1-5.8L3.5 9.2l5.9-.9L12 3Z'],
  offline: ['M3 3l18 18', 'M8.5 8.5A6 6 0 0 0 6 12M2 8.5a11 11 0 0 1 4-2.8M22 8.5a11 11 0 0 0-6-3M12 20h.01'],
  wifi: ['M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0M12 19h.01'],
  cap: ['M22 9 12 5 2 9l10 4 10-4Z', 'M6 11v4c0 1.5 2.7 3 6 3s6-1.5 6-3v-4'],
  flask: ['M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3'],
  robot: ['M9 12h.01M15 12h.01', 'M6 8h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z', 'M12 4v4M12 4a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z'],
  wrench: ['M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2-2 2.5-2.5Z'],
  shieldx: ['M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3Z', 'M9.5 9.5l5 5M14.5 9.5l-5 5'],
  power: ['M12 3v9', 'M18 6a8 8 0 1 1-12 0'],
  clock: ['M12 7v5l3 2'],
  block: ['M5 5l14 14'],
  list: ['M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01'],
  inbox: ['M22 12h-6l-2 3h-4l-2-3H2', 'M5 5h14l3 7v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-6l3-7Z'],
  dots: ['M5 12h.01M12 12h.01M19 12h.01'],
  grid: ['M4 4h7v7H4V4Zm9 0h7v7h-7V4ZM4 13h7v7H4v-7Zm9 0h7v7h-7v-7Z'],
  more: ['M6 12h.01M12 12h.01M18 12h.01'],
}
const C = { clock: [[12, 12, 9]], block: [[12, 12, 9]], dot: [[12, 12, 4]] }
const paths = computed(() => P[props.name] || [])
const circles = computed(() => C[props.name] || [])
</script>
<style scoped>
.fic{display:inline-block;vertical-align:-0.14em;flex:none}
</style>
