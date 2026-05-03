<template>
  <div v-if="$route.name === 'login'"><router-view/></div>
  <div v-else-if="authChecked && !isAdmin" class="min-h-screen flex items-center justify-center">
    <div class="bg-dark-100 p-8 rounded-xl border border-danger w-96 text-center">
      <div class="text-lg font-bold text-danger mb-2">访问被拒</div>
      <div class="text-sm text-text-secondary mb-4">OpenCLAW 控制台仅限超级管理员/系统管理员访问</div>
      <div class="text-xs text-text-tertiary">当前角色：{{ me?.role || '未知' }}</div>
      <button @click="logout" class="mt-4 px-4 py-2 bg-primary text-dark-300 rounded text-sm">返回登录</button>
    </div>
  </div>
  <div v-else class="min-h-screen flex flex-col">
    <AnnouncementBanner />
    <header class="bg-dark-200 border-b border-border-primary px-3 sm:px-6 py-2 sm:py-3 flex flex-wrap items-center justify-between gap-2 overflow-x-hidden">
      <div class="flex items-center gap-6">
        <div class="flex items-center gap-2">
          <img src="/logo.png" alt="OpenCLAW" class="w-8 h-8 object-contain" />
          <div>
            <div class="font-bold text-base leading-tight">OpenCLAW</div>
            <div class="text-[10px] text-text-tertiary leading-tight">量化智能体控制台</div>
          </div>
        </div>
        <nav class="flex gap-1 text-sm overflow-x-auto scrollbar-hide">
          <router-link v-for="n in nav" :key="n.path" :to="n.path"
            class="px-3 py-1.5 rounded hover:bg-dark-100 transition relative whitespace-nowrap"
            active-class="bg-dark-100 text-primary">
            {{ n.label }}
            <span v-if="n.path === '/dashboard' && targetStore.alerts.unacked_count"
              class="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-danger text-white text-[9px] font-bold">
              {{ targetStore.alerts.unacked_count > 99 ? '99+' : targetStore.alerts.unacked_count }}
            </span>
          </router-link>
        </nav>
      </div>

      <!-- LLM stats widget + user -->
      <div class="flex items-center gap-4">
        <div class="hidden sm:flex items-center gap-3 px-3 py-1.5 bg-dark-100 rounded border border-border-primary text-xs">
          <div class="flex flex-col leading-tight">
            <span class="text-text-tertiary text-[10px]">模型</span>
            <span class="font-mono font-semibold text-primary">{{ llm?.model || '--' }}</span>
          </div>
          <div class="w-px h-6 bg-border-primary"></div>
          <div class="flex flex-col leading-tight">
            <span class="text-text-tertiary text-[10px]">今日 tokens</span>
            <span class="font-mono">{{ fmtInt(llm?.tokens_today?.total) }}
              <span class="text-text-tertiary">({{ llm?.tokens_today?.calls || 0 }}次)</span>
            </span>
          </div>
          <div class="w-px h-6 bg-border-primary"></div>
          <div class="flex flex-col leading-tight">
            <span class="text-text-tertiary text-[10px]">今日消费</span>
            <span class="font-mono font-semibold text-warning">
              {{ relayCost?.today?.cost_usd != null ? '$' + relayCost.today.cost_usd.toFixed(2) : '--' }}
            </span>
          </div>
          <div class="w-px h-6 bg-border-primary"></div>
          <div class="flex flex-col leading-tight">
            <span class="text-text-tertiary text-[10px]">
              {{ llm?.balance?.source === 'chesspnt_self' ? '钱包余额(实时)' : '中转站余额' }}
            </span>
            <span class="font-mono font-semibold" :class="balanceColor">
              {{ llm?.balance?.balance_usd != null ? '$' + llm.balance.balance_usd.toFixed(2) : '--' }}
            </span>
          </div>
          <div v-if="llm?.balance?.low_balance" class="px-1.5 py-0.5 bg-danger/20 text-danger rounded text-[10px] font-bold">低</div>
        </div>

        <span class="flex items-center gap-1.5 text-xs">
          <span class="w-2 h-2 rounded-full" :class="modeColor"></span>
          <span class="text-text-secondary">{{ modeLabel }}</span>
        </span>
        <span class="text-xs text-text-tertiary">{{ me?.username }} · {{ me?.role }}</span>
        <button @click="logout" class="text-xs text-text-tertiary hover:text-text-primary">退出</button>
      </div>
    </header>
    <main class="flex-1 p-3 sm:p-6"><router-view/></main>
    <HustleChat v-if="isAdmin" />
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '@/api'
import AnnouncementBanner from '@/components/AnnouncementBanner.vue'
import HustleChat from '@/components/HustleChat.vue'
import { useTargetStore } from '@/stores/targetStore.js'

const router = useRouter()
const route = useRoute()
const targetStore = useTargetStore()
const nav = [
  { path: '/dashboard', label: '实时监控' },
  { path: '/decisions', label: '决策流' },
  { path: '/proposals', label: '提议中心' },
  { path: '/risk', label: '风控中心' },
  { path: '/infra', label: '基础设施' },
]
const me = ref(null)
const authChecked = ref(false)
const llm = ref(null)
const relayCost = ref(null)
const status = ref(null)

const isAdmin = computed(() => me.value?.is_admin === true)
const modeLabel = computed(() => ({ shadow: 'Shadow', semi: '半自动', auto: '全自动', off: '已停机' })[status.value?.mode] || '--')
const modeColor = computed(() => ({ shadow: 'bg-yellow-400', semi: 'bg-blue-400', auto: 'bg-success', off: 'bg-text-tertiary' })[status.value?.mode] || 'bg-text-tertiary')
const balanceColor = computed(() => {
  const b = llm.value?.balance?.balance_usd
  if (b == null) return 'text-text-primary'
  if (b < 20) return 'text-danger'
  if (b < 100) return 'text-warning'
  return 'text-success'
})

function fmtInt(n) { return n != null ? Number(n).toLocaleString() : '--' }

async function checkAuth() {
  try {
    const r = await api.get('/api/v1/agent/whoami')
    me.value = r.data
    authChecked.value = true
    if (!r.data.is_admin) return
    await refresh()
    targetStore.refresh()
  } catch (e) {
    if (e.response?.status === 401) { logout(); return }
    me.value = { is_admin: false, role: (e.response?.status === 401 ? '会话已过期, 请重新登录' : (e.response?.data?.detail || '--')) }
    authChecked.value = true
  }
}

async function refresh() {
  try {
    const [l, s, rc] = await Promise.all([
      api.get('/api/v1/agent/llm-stats').catch(() => null),
      api.get('/api/v1/agent/status').catch(() => null),
      api.get('/api/v1/agent/relay/cost-summary').catch(() => null),
    ])
    if (l) llm.value = l.data
    if (s) status.value = s.data
    if (rc) relayCost.value = rc.data
  } catch (e) { console.error(e) }
}

function logout() {
  localStorage.removeItem('access_token')
  router.push('/login')
}

let timer, alertTimer
onMounted(() => {
  if (route.name !== 'login') checkAuth()
  timer = setInterval(() => { if (isAdmin.value) refresh() }, 15000)
  alertTimer = setInterval(() => { if (isAdmin.value) targetStore.loadAlerts() }, 30000)
})
onUnmounted(() => { clearInterval(timer); clearInterval(alertTimer) })

watch(() => route.name, (n, o) => {
  if (o === 'login' && n !== 'login') {
    authChecked.value = false
    me.value = null
    checkAuth()
  }
})
</script>
