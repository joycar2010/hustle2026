<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed top-0 left-0 right-0 z-[99998] flex items-center justify-center py-2 px-4 shadow-lg"
         style="background-color: rgba(180,83,9,0.98)">
      <div class="text-sm font-bold text-white text-center leading-snug">
        ⚠️ {{ reason }} — 自动交易已暂停,连接恢复后自动继续<span v-if="count > 1">({{ count }} 个策略)</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()
// strategy_type -> reason；非空即显示横幅
const pausedMap = ref({})
const reason = ref('')

const visible = computed(() => Object.keys(pausedMap.value).length > 0)
const count = computed(() => Object.keys(pausedMap.value).length)

// 连接掉线 -> 后端推 ws:user_event(type=connection_pause, data.paused=true/false), 实时显示/隐藏(无需刷新)
watch(() => marketStore.lastMessage, (msg) => {
  if (msg && msg.type === 'connection_pause' && msg.data) {
    const st = msg.data.strategy_type || 'unknown'
    const m = { ...pausedMap.value }
    if (msg.data.paused) {
      m[st] = msg.data.reason || '连接中断'
      reason.value = msg.data.reason || '连接中断'
    } else {
      delete m[st]
    }
    pausedMap.value = m
  }
})
</script>
