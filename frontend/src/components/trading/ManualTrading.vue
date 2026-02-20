<template>
  <div class="h-full flex flex-col p-3">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-bold">紧急手动交易</h3>
      <div class="flex items-center space-x-1">
        <div class="w-2 h-2 rounded-full bg-[#f6465d] animate-pulse"></div>
        <span class="text-xs text-[#f6465d] font-bold">紧急模式</span>
      </div>
    </div>
    <div class="space-y-3">
      <!-- Exchange Selection -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">交易平台</label>
        <select
          v-model="tradeForm.exchange"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
        >
          <option value="binance">Binance</option>
          <option value="bybit">Bybit MT5</option>
        </select>
      </div>

      <!-- Symbol -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">交易对</label>
        <input
          v-model="tradeForm.symbol"
          type="text"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
          placeholder="XAUUSDT"
        />
      </div>

      <!-- Quantity -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">数量</label>
        <input
          v-model.number="tradeForm.quantity"
          type="number"
          step="0.01"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
        />
      </div>

      <!-- Price -->
      <div>
        <label class="text-xs text-gray-400 mb-1 block">价格（留空为市价）</label>
        <input
          v-model.number="tradeForm.price"
          type="number"
          step="0.01"
          class="w-full bg-[#252930] border border-[#2b3139] rounded px-3 py-2 text-sm focus:border-[#f0b90b] focus:outline-none"
          placeholder="市价"
        />
      </div>

      <!-- Action Buttons -->
      <div class="grid grid-cols-2 gap-2">
        <button
          @click="executeTrade('buy')"
          class="px-4 py-3 bg-[#0ecb81] text-white rounded font-bold hover:bg-[#0db774] transition-colors"
        >
          买入开多
        </button>
        <button
          @click="executeTrade('sell')"
          class="px-4 py-3 bg-[#f6465d] text-white rounded font-bold hover:bg-[#e03d52] transition-colors"
        >
          卖出开空
        </button>
      </div>

      <!-- Quick Actions -->
      <div class="pt-3 border-t border-[#2b3139] space-y-2">
        <button
          @click="closeAllPositions"
          class="w-full px-4 py-2 bg-[#f6465d] text-white rounded text-sm font-bold hover:bg-[#e03d52] transition-colors"
        >
          ⚠️ 平仓所有持仓
        </button>
        <button
          @click="cancelAllOrders"
          class="w-full px-4 py-2 bg-[#252930] text-white rounded text-sm hover:bg-[#2b3139] transition-colors"
        >
          取消所有挂单
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const tradeForm = ref({
  exchange: 'binance',
  symbol: 'XAUUSDT',
  quantity: 0.1,
  price: null,
})

function executeTrade(side) {
  console.log('Executing trade:', { ...tradeForm.value, side })
  // API call to execute trade
}

function closeAllPositions() {
  if (confirm('确定要平仓所有持仓吗？')) {
    console.log('Closing all positions')
    // API call
  }
}

function cancelAllOrders() {
  if (confirm('确定要取消所有挂单吗？')) {
    console.log('Cancelling all orders')
    // API call
  }
}
</script>