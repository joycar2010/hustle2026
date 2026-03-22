<template>
  <!-- 移动端底部 Tab Bar + PC端隐藏 -->
  <nav class="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-dark-100 border-t border-border-primary safe-bottom">
    <div class="flex items-center justify-around px-2 py-1">
      <router-link v-for="item in tabs" :key="item.path" :to="item.path"
        class="flex flex-col items-center gap-0.5 px-4 py-2 rounded-xl transition-colors min-w-0"
        :class="isActive(item.path) ? 'text-primary' : 'text-text-tertiary hover:text-text-secondary'">
        <span class="text-2xl leading-none">{{ item.icon }}</span>
        <span class="text-xs whitespace-nowrap font-medium">{{ item.label }}</span>
      </router-link>

      <!-- 退出按钮 -->
      <button @click="handleLogout" class="flex flex-col items-center gap-0.5 px-4 py-2 rounded-xl text-text-tertiary hover:text-danger transition-colors">
        <span class="text-2xl leading-none">⏻</span>
        <span class="text-xs font-medium">退出</span>
      </button>
    </div>
  </nav>

  <!-- PC / 平板端左侧或顶部导航由各页面 header 实现，此处无需重复 -->
</template>

<script setup>
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const route  = useRoute()
const auth   = useAuthStore()

const tabs = [
  { path: '/',        label: '实时收益', icon: '💰' },
  { path: '/history', label: '交易历史', icon: '📊' },
]

function isActive(path) { return route.path === path }
function handleLogout() { auth.logout(); router.push('/login') }
</script>

<style scoped>
.safe-bottom { padding-bottom: env(safe-area-inset-bottom, 0px); }
</style>
