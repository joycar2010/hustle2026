<template>
  <div class="h-full flex flex-col p-2 md:p-3 min-h-0">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-bold">紧急手动交易</h3>
      <div class="flex items-center space-x-1">
        <div class="w-2 h-2 rounded-full bg-[#f6465d] animate-pulse"></div>
        <span class="text-xs text-[#f6465d] font-bold">紧急模式</span>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto space-y-3 min-h-0">
      <!-- Exchange Selection -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">交易平台</label>
        <select
          v-model="exchange"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
        >
          <option value="binance">Binance (XAUUSDT)</option>
          <option value="bybit">Bybit MT5 (XAUUSD.s)</option>
        </select>
      </div>

      <!-- Quantity -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">下单总手数 (XAU)</label>
        <input
          v-model.number="quantity"
          type="number"
          step="1"
          min="1"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
          placeholder="1"
        />
        <div class="text-xs text-gray-500 mt-1">
          Bybit 实际下单量: {{ xauToLot(quantity).toFixed(2) }} Lot
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="grid grid-cols-2 gap-2">
        <button
          @click="executeTrade('buy')"
          :disabled="loading"
          class="px-4 py-2 bg-[#0ecb81] text-white rounded text-sm font-bold hover:bg-[#0db774] transition-colors disabled:opacity-50"
        >
          买入开多
        </button>
        <button
          @click="executeTrade('sell')"
          :disabled="loading"
          class="px-4 py-2 bg-[#f6465d] text-white rounded text-sm font-bold hover:bg-[#e03d52] transition-colors disabled:opacity-50"
        >
          卖出开空
        </button>
      </div>

      <!-- Status message -->
      <div v-if="statusMsg" :class="['text-xs px-2 py-1 rounded', statusOk ? 'text-[#0ecb81] bg-[#0ecb81]/10' : 'text-[#f6465d] bg-[#f6465d]/10']">
        {{ statusMsg }}
      </div>

      <!-- Quick Actions -->
      <div class="pt-3 border-t border-[#2b3139]">
        <div class="grid grid-cols-2 gap-2">
          <button
            @click="closeAllPositions"
            :disabled="loading"
            class="px-4 py-1.5 bg-[#f6465d] text-white rounded text-sm font-bold hover:bg-[#e03d52] transition-colors disabled:opacity-50"
          >
            ⚠️ 平仓所有持仓
          </button>
          <button
            @click="cancelAllOrders"
            :disabled="loading"
            class="px-4 py-1.5 bg-[#252930] text-white rounded text-sm hover:bg-[#2b3139] transition-colors disabled:opacity-50"
          >
            取消所有挂单
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import api from '@/services/api'
import { xauToLot, convertForPlatform } from '@/composables/useQuantityConverter'

const exchange = ref('binance')
const quantity = ref(1)
const loading = ref(false)
const statusMsg = ref('')
const statusOk = ref(true)

function showStatus(msg, ok = true) {
  statusMsg.value = msg
  statusOk.value = ok
  setTimeout(() => { statusMsg.value = '' }, 4000)
}

async function executeTrade(side) {
  if (loading.value) return
  loading.value = true
  try {
    const actualQuantity = convertForPlatform(quantity.value, exchange.value)

    await api.post('/api/v1/trading/manual/order', {
      exchange: exchange.value,
      side,
      quantity: actualQuantity,
    })
    showStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送`, true)
  } catch (e) {
    showStatus(e.response?.data?.detail || '下单失败', false)
  } finally {
    loading.value = false
  }
}

async function closeAllPositions() {
  if (!confirm('确定要平仓所有持仓吗？')) return
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/close-all')
    showStatus(`平仓指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
  } catch (e) {
    showStatus(e.response?.data?.detail || '平仓失败', false)
  } finally {
    loading.value = false
  }
}

async function cancelAllOrders() {
  if (!confirm('确定要取消所有挂单吗？')) return
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/cancel-all')
    showStatus(`撤单指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
  } catch (e) {
    showStatus(e.response?.data?.detail || '撤单失败', false)
  } finally {
    loading.value = false
  }
}
</script>
