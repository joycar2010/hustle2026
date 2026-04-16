<template>
  <!-- Mobile: bottom tab bar -->
  <nav class="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-dark-100 border-t border-border-primary safe-bottom">
    <div class="flex items-center justify-around px-1 py-1">
      <router-link v-for="item in tabs" :key="item.path" :to="item.path"
        class="flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-xl transition-colors"
        :class="isActive(item.path) ? 'text-primary' : 'text-text-tertiary hover:text-text-secondary'">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24" v-html="item.svg"></svg>
        <span class="text-[10px] font-medium">{{ item.label }}</span>
      </router-link>
      <button @click="handleLogout" class="flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-xl text-text-tertiary hover:text-danger transition-colors">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
        <span class="text-[10px] font-medium">退出</span>
      </button>
    </div>
  </nav>

  <!-- PC: horizontal nav bar at bottom -->
  <nav class="hidden md:block fixed bottom-0 left-0 right-0 z-50 bg-dark-100 border-t border-border-primary">
    <div class="max-w-5xl mx-auto flex items-center justify-center gap-1 px-4 py-2">
      <router-link v-for="item in tabs" :key="item.path" :to="item.path"
        class="flex items-center gap-2 px-5 py-2 rounded-xl transition-colors"
        :class="isActive(item.path) ? 'bg-primary/10 text-primary' : 'text-text-tertiary hover:text-text-secondary hover:bg-dark-50'">
        <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24" v-html="item.svg"></svg>
        <span class="text-sm font-medium">{{ item.label }}</span>
      </router-link>
      <button @click="handleLogout" class="flex items-center gap-2 px-5 py-2 rounded-xl text-text-tertiary hover:text-danger hover:bg-dark-50 transition-colors ml-4">
        <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
        <span class="text-sm font-medium">退出</span>
      </button>
    </div>
  </nav>
</template>

<script setup>
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const tabs = [
  { path: '/',        label: '总览',   svg: '<path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1"/>' },
  { path: '/daily',   label: '日收益', svg: '<path stroke-linecap="round" stroke-linejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>' },
  { path: '/weekly',  label: '周收益', svg: '<path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>' },
  { path: '/monthly', label: '月收益', svg: '<path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>' },
]

function isActive(path) { return route.path === path }
function handleLogout() { auth.logout(); router.push('/login') }
</script>

<style scoped>
.safe-bottom { padding-bottom: env(safe-area-inset-bottom, 0px); }
</style>
