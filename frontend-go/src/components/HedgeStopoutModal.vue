<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-[99999] flex items-center justify-center"
         style="background-color: rgba(91,12,12,0.985)">
      <div class="max-w-md w-full mx-4 bg-[#1a0707] border-2 border-[#ef4444] rounded-2xl p-6 shadow-2xl">
        <div class="text-center mb-4">
          <div class="text-5xl mb-2">⚠️</div>
          <div class="text-2xl font-extrabold text-[#fca5a5]">对冲腿被强平 — 单腿风险!</div>
        </div>
        <div class="text-sm text-[#fecaca] space-y-2 mb-4 font-mono">
          <div>对冲账号: <b class="text-white">{{ a.account_name }}</b> ({{ a.pair_code }})</div>
          <div>被强平: <b class="text-[#fbbf24]">{{ a.so_volume }}</b> 手 — 保证金不足被券商强平</div>
          <div>币安主腿裸露: <b class="text-[#fbbf24]">{{ sideCn }} {{ a.naked_qty }}</b> XAU</div>
          <div class="text-[10px] text-[#f87171] break-all">{{ a.so_comment }}</div>
        </div>
        <div class="text-[11px] text-[#fca5a5] mb-4 leading-relaxed">
          请核对实际情况后选择：<b>确认收口</b> 将以币安 <b>maker 限价</b>平掉裸露的币安主腿（数量=被强平量）；
          或 <b>取消</b> 关闭本提示、稍后自行择机手动处理。
        </div>
        <div class="flex gap-3">
          <button @click="closeout" :disabled="busy"
                  class="flex-1 py-3 rounded-xl bg-[#ef4444] hover:bg-[#dc2626] text-white font-bold disabled:opacity-50 transition-colors">
            {{ busy ? '收口中...' : '确认收口' }}
          </button>
          <button @click="dismiss" :disabled="busy"
                  class="flex-1 py-3 rounded-xl bg-[#3f3f46] hover:bg-[#52525b] text-white font-bold disabled:opacity-50 transition-colors">
            取消
          </button>
        </div>
        <div v-if="result" class="mt-3 text-center text-xs font-mono"
             :class="resultOk ? 'text-[#4ade80]' : 'text-[#fca5a5]'">{{ result }}</div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const marketStore = useMarketStore()
const visible = ref(false)
const a = ref({})
const busy = ref(false)
const result = ref('')
const resultOk = ref(false)

const sideCn = computed(() =>
  a.value.naked_side === 'long' ? '多' : (a.value.naked_side === 'short' ? '空' : (a.value.naked_side || '')))

watch(() => marketStore.lastMessage, (msg) => {
  if (msg && msg.type === 'hedge_stopout' && msg.data) {
    a.value = msg.data
    result.value = ''
    resultOk.value = false
    busy.value = false
    visible.value = true
  }
})

async function closeout() {
  busy.value = true
  result.value = ''
  try {
    const r = await api.post('/api/v1/strategies/hedge/closeout', { pair_code: a.value.pair_code })
    resultOk.value = true
    result.value = '已提交收口: ' + (r.data && r.data.message ? r.data.message : '成功')
    setTimeout(() => { visible.value = false }, 2800)
  } catch (e) {
    resultOk.value = false
    const detail = e && e.response && e.response.data && e.response.data.detail
    result.value = '收口失败: ' + (detail || (e && e.message) || '未知错误')
  } finally {
    busy.value = false
  }
}

function dismiss() {
  visible.value = false
}
</script>
