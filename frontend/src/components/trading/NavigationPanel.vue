<template>
  <div class="p-4 space-y-2 border-t border-[#2b3139]">
    <h3 class="text-sm font-bold mb-3 text-gray-400">系统状态</h3>

    <button
      v-for="item in navItems"
      :key="item.id"
      @click="handleNavClick(item.id)"
      :class="[
        'w-full px-4 py-3 rounded text-left transition-all',
        activeNav === item.id
          ? 'bg-[#f0b90b]/20 text-[#f0b90b] border border-[#f0b90b]'
          : 'bg-[#252930] hover:bg-[#2b3139] text-gray-300'
      ]"
    >
      <div class="flex items-center justify-between">
        <div class="flex items-center space-x-2">
          <component :is="item.icon" class="w-5 h-5" />
          <span class="text-sm font-medium">{{ item.label }}</span>
        </div>
        <div v-if="item.badge" :class="['text-xs px-2 py-0.5 rounded', item.badgeClass]">
          {{ item.badge }}
        </div>
      </div>
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const activeNav = ref('strategy')

const navItems = [
  {
    id: 'strategy',
    label: '策略控制',
    icon: 'StrategyIcon',
    badge: '运行中',
    badgeClass: 'bg-[#0ecb81] text-white',
  },
  {
    id: 'risk',
    label: '风控状态',
    icon: 'RiskIcon',
    badge: '正常',
    badgeClass: 'bg-[#0ecb81] text-white',
  },
]

function handleNavClick(id) {
  activeNav.value = id
  // Emit event or navigate
}

// Icon components
const AccountIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" /></svg>`
}

const StrategyIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>`
}

const RiskIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>`
}
</script>