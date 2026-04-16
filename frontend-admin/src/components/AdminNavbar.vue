<template>
  <nav class="bg-dark-100 border-b border-border-primary sticky top-0 z-50">
    <div class="container mx-auto px-4">
      <div class="flex items-center justify-between h-16">

        <!-- Logo -->
        <div class="flex items-center space-x-6">
          <router-link to="/" class="flex items-center space-x-3 flex-shrink-0">
            <div class="w-10 h-10 bg-gradient-to-br from-red-600 to-red-800 rounded-lg flex items-center justify-center shadow-lg">
              <span class="text-white font-bold text-lg">管</span>
            </div>
            <div class="hidden md:block">
              <div class="text-lg font-bold text-text-primary">HustleXAU Admin</div>
              <div class="text-xs text-red-400">总控管理平台</div>
            </div>
          </router-link>

          <!-- Desktop Nav -->
          <div class="hidden lg:flex space-x-1">
            <router-link
              v-for="item in navItems" :key="item.path"
              :to="item.path"
              class="admin-nav-link"
              :title="item.dblClickHint"
              @dblclick.prevent="item.onDblClick && item.onDblClick()"
            >
              <span class="text-base">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
              <span v-if="item.dblClickHint" class="text-xs text-text-tertiary hidden xl:inline ml-1" title="双击在新标签页打开">⧉</span>
            </router-link>
          </div>
        </div>

        <!-- Right: user + role badge -->
        <div class="flex items-center space-x-3">
          <span v-if="userRole" class="hidden md:inline-flex items-center px-2 py-1 bg-red-900/40 text-red-300 rounded text-xs font-medium border border-red-800/50">
            {{ userRole }}
          </span>
          <div class="relative" ref="userMenuRef">
            <button @click="menuOpen = !menuOpen" class="flex items-center space-x-2 px-3 py-2 rounded-lg hover:bg-dark-50 transition-colors">
              <div class="w-8 h-8 bg-gradient-to-br from-red-600 to-red-800 rounded-full flex items-center justify-center">
                <span class="text-white font-bold text-sm">{{ userInitial }}</span>
              </div>
              <span class="hidden md:block text-sm font-medium">{{ username }}</span>
              <svg class="w-4 h-4 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            <transition enter-active-class="transition ease-out duration-100" enter-from-class="opacity-0 scale-95" enter-to-class="opacity-100 scale-100" leave-active-class="transition ease-in duration-75" leave-from-class="opacity-100 scale-100" leave-to-class="opacity-0 scale-95">
              <div v-if="menuOpen" class="absolute right-0 mt-2 w-44 bg-dark-100 rounded-lg shadow-lg border border-border-primary py-1">
                <div class="px-4 py-2 text-xs text-text-tertiary border-b border-border-secondary">{{ username }}</div>
                <a href="https://go.hustle2026.xyz" target="_blank" class="flex items-center gap-2 w-full text-left px-4 py-2 text-sm hover:bg-dark-50 transition-colors">
                  <span>🔗</span><span>切换到交易面板</span>
                </a>
                <button @click="handleLogout" class="flex items-center gap-2 w-full text-left px-4 py-2 text-sm hover:bg-dark-50 text-danger transition-colors">
                  <span>⏻</span><span>退出登录</span>
                </button>
              </div>
            </transition>
          </div>

          <!-- Mobile menu button -->
          <button @click="mobileOpen = !mobileOpen" class="lg:hidden p-2 rounded-lg hover:bg-dark-50">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path v-if="!mobileOpen" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
              <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Mobile Menu -->
      <transition enter-active-class="transition ease-out duration-200" enter-from-class="opacity-0 -translate-y-2" enter-to-class="opacity-100 translate-y-0">
        <div v-if="mobileOpen" class="lg:hidden py-3 space-y-1 border-t border-border-secondary">
          <router-link
            v-for="item in navItems" :key="item.path"
            :to="item.path"
            @click="mobileOpen = false"
            class="flex items-center gap-3 px-4 py-3 rounded-lg text-text-secondary hover:text-text-primary hover:bg-dark-50 transition-colors"
          >
            <span>{{ item.icon }}</span>
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </transition>
    </div>
  </nav>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()
const menuOpen = ref(false)
const mobileOpen = ref(false)
const userMenuRef = ref(null)

const username = computed(() => authStore.user?.username || '...')
const userRole = computed(() => authStore.userRole || '')
const userInitial = computed(() => {
  const n = authStore.user?.username
  return n ? n.charAt(0).toUpperCase() : '?'
})

const navItems = [
  {
    path: '/', label: '总控面板', icon: '🖥️',
  },
  {
    path: '/ws-monitor', label: 'WebSocket监控', icon: '📡',
    dblClickHint: '双击在新标签页打开',
    onDblClick: () => window.open(window.location.origin + '/ws-monitor', '_blank')
  },
  { path: '/spread',     label: '点差记录分析', icon: '📊' },
  { path: '/strategies', label: '策略配置',     icon: '⚙️' },
  { path: '/hedging',    label: '对冲平台管理', icon: '🔄' },
  { path: '/users',      label: '用户管理',     icon: '👥' },
  { path: '/system',     label: '系统管理',     icon: '🔧' },
]

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

function handleClickOutside(e) {
  if (userMenuRef.value && !userMenuRef.value.contains(e.target)) menuOpen.value = false
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
</script>

<style scoped>
.admin-nav-link {
  @apply flex items-center space-x-1.5 px-3 py-2 rounded-lg text-sm text-text-secondary hover:text-text-primary hover:bg-dark-50 transition-all duration-200 whitespace-nowrap;
}
.router-link-active.admin-nav-link {
  @apply text-red-400 bg-red-900/20 font-medium;
}
</style>
