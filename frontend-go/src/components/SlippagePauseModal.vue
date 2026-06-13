<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[99999] flex items-center justify-center"
         style="background-color: rgba(60,30,5,0.985)">
      <div class="max-w-md w-full mx-4 bg-[#1a1207] border-2 border-[#f59e0b] rounded-2xl p-6 shadow-2xl">
        <div class="text-center mb-4">
          <div class="text-5xl mb-2">🛑</div>
          <div class="text-2xl font-extrabold text-[#fcd34d]">滑点保护 · 二级暂停</div>
        </div>
        <div class="text-sm text-[#fde68a] space-y-2 mb-4 font-mono">
          <div>交易对: <b class="text-white">{{ d.pair_code }}</b><span v-if="d.strategy_type"> · {{ d.strategy_type }}</span></div>
          <div>触发原因: <b class="text-[#fbbf24]">{{ d.reason }}</b></div>
          <div>本笔滑点: <b class="text-[#fbbf24]">{{ fmt(d.slippage) }}</b>(实际点差 {{ fmt(d.actual_spread) }} / 阈值 {{ fmt(d.threshold) }})</div>
        </div>
        <div class="text-[11px] text-[#fcd34d] mb-4 leading-relaxed">
          连续大滑点已触发<b>二级暂停</b>,该交易对所有开/平仓单已被拦截。请选择:<b>确认</b> 强制恢复、立即继续自动交易;
          或 <b>取消</b> 停止该交易对的自动交易。
        </div>
        <div class="flex gap-3">
          <button @click="resume" :disabled="!!busy"
                  class="flex-1 py-3 rounded-xl bg-[#f59e0b] hover:bg-[#d97706] text-white font-bold disabled:opacity-50 transition-colors">
            {{ busy === 'resume' ? '恢复中...' : '确认 (继续)' }}
          </button>
          <button @click="stop" :disabled="!!busy"
                  class="flex-1 py-3 rounded-xl bg-[#3f3f46] hover:bg-[#52525b] text-white font-bold disabled:opacity-50 transition-colors">
            {{ busy === 'stop' ? '停止中...' : '取消 (停止)' }}
          </button>
        </div>
        <div v-if="result" class="mt-3 text-center text-xs font-mono"
             :class="resultOk ? 'text-[#4ade80]' : 'text-[#fca5a5]'">{{ result }}</div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const marketStore = useMarketStore()
const visible = ref(false)
const d = ref({})
const busy = ref('')
const result = ref('')
const resultOk = ref(false)

const fmt = (v) => (v === undefined || v === null || isNaN(Number(v))) ? '-' : Number(v).toFixed(2)

// 二级滑点暂停 → 立即弹框(经 ws:user_event 推送, 无需刷新)。一级不阻断。
watch(() => marketStore.lastMessage, (msg) => {
  if (msg && msg.type === 'slippage_pause' && msg.data && Number(msg.data.level) === 2) {
    d.value = msg.data
    result.value = ''
    resultOk.value = false
    busy.value = ''
    visible.value = true
  }
})

async function resume() {
  busy.value = 'resume'
  result.value = ''
  try {
    const r = await api.post(`/api/v1/strategies/slippage-pause/${d.value.pair_code}/resume`)
    resultOk.value = true
    result.value = (r.data && r.data.message) ? r.data.message : '已强制恢复, 自动交易继续'
    setTimeout(() => { visible.value = false }, 1500)
  } catch (e) {
    resultOk.value = false
    const detail = e && e.response && e.response.data && e.response.data.detail
    result.value = '恢复失败: ' + (detail || (e && e.message) || '未知错误')
  } finally {
    busy.value = ''
  }
}

async function stop() {
  busy.value = 'stop'
  result.value = ''
  try {
    const r = await api.post(`/api/v1/strategies/slippage-pause/${d.value.pair_code}/stop`)
    resultOk.value = true
    result.value = (r.data && r.data.message) ? r.data.message : '已停止自动交易'
    setTimeout(() => { visible.value = false }, 1800)
  } catch (e) {
    resultOk.value = false
    const detail = e && e.response && e.response.data && e.response.data.detail
    result.value = '停止失败: ' + (detail || (e && e.message) || '未知错误')
  } finally {
    busy.value = ''
  }
}
</script>
