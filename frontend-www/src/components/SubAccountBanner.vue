<template>
  <div v-if="auth.isSubAccount && auth.subBanner"
       class="bg-purple-900/25 border-b border-purple-500/40 px-3 py-1.5 text-xs text-purple-200 text-center">
    <span class="font-semibold">📊 子账号视图</span>
    <span v-if="parentCount > 1" class="ml-1 px-1.5 py-0.5 rounded bg-purple-500/40 text-white text-[10px]">
      M2M · {{ parentCount }} 个父账号
    </span>
    · 主父按份额 <span class="font-mono text-white">{{ (auth.subBanner.multiplier * 100).toFixed(2) }}%</span>
    · 总投入 <span class="font-mono">¥{{ Number(auth.subBanner.invested_cny).toLocaleString() }}</span>
    ≈ <span class="font-mono">{{ Number(auth.subBanner.invested_usdt).toFixed(2) }} USDT</span>
    · 总估值 <span class="font-mono" :class="currentGte ? 'text-green-300' : 'text-red-300'">
      {{ Number(auth.subBanner.current_value_usdt).toFixed(2) }} USDT
    </span>
    <span class="ml-2 text-[10px] text-purple-300/70">(仅查看 · 不构成实际持有)</span>
    <div v-if="parentCount > 1" class="text-[10px] text-purple-300/80 mt-1">
      <span v-for="(s, i) in auth.subBanner.subscriptions" :key="s.subscription_id">
        <span v-if="i > 0" class="mx-1">·</span>
        <span :class="s.is_primary ? 'text-white font-semibold' : ''">{{ s.parent_username }}</span>
        <span class="font-mono"> ¥{{ Number(s.invested_cny).toLocaleString() }} → {{ Number(s.current_value_usdt).toFixed(2) }} USDT</span>
      </span>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth.js'
const auth = useAuthStore()
const parentCount = computed(() => auth.subBanner?.subscriptions?.length || 0)
const currentGte = computed(() => {
  const b = auth.subBanner
  if (!b) return true
  return Number(b.current_value_usdt) >= Number(b.invested_usdt)
})
</script>
