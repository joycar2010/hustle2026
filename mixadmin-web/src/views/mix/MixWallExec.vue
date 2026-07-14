<template>
  <!-- 三分屏V2·屏2(z2Kwl)持仓与执行:设计=tlOCA 同骨架(单屏版即屏2复制+页签),
       故 1:1 复用主控台组件,墙模式全屏铺满(?token= 引导同源 API 头)。 -->
  <div class="wall2" v-if="authed">
    <MixDashboard />
  </div>
  <div v-else class="gate">屏2 · 持仓与执行<br /><small>URL 需携带 ?token=(只读墙令牌,后端校验)</small></div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import MixDashboard from './MixDashboard.vue'

const route = useRoute()
const authed = ref(!!route.query.token || !!localStorage.getItem('mix_token'))
if (route.query.token) localStorage.setItem('mix_token', String(route.query.token))
</script>

<style scoped>
.wall2 { min-height: 100vh; background: var(--mix-bg, #0B0E11); padding: 10px 16px 12px; }
.gate { min-height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center;
  background: #0B0E11; color: #848E9C; font-size: 15px; }
</style>
