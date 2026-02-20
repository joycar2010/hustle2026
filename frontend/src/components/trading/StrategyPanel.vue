<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="p-3 border-b border-[#2b3139]">
      <h3 class="text-sm font-bold">{{ type === 'forward' ? '正向套利策略' : '反向套利策略' }}</h3>
    </div>

    <div class="flex-1 overflow-y-auto p-3 space-y-3">
      <!-- Top Info Bar -->
      <div class="bg-[#252930] rounded p-3">
        <div class="grid grid-cols-3 gap-3">
          <!-- Spread Display -->
          <div class="text-center">
            <div class="text-xs text-gray-400 mb-1">
              {{ type === 'reverse' ? '做多Bybit点差' : '做多Binance点差' }}
            </div>
            <div :class="['text-2xl font-mono font-bold', type === 'reverse' ? 'text-[#0ecb81]' : 'text-[#f6465d]']">
              {{ currentSpread.toFixed(2) }} USDT
            </div>
          </div>

          <!-- Binance Available Assets -->
          <div>
            <div class="text-xs text-gray-400 mb-1">Binance可用资产</div>
            <div class="text-base font-mono font-bold">
              {{ formatNumber(binanceAssets) }} USDT
            </div>
          </div>

          <!-- Bybit MT5 Available Assets -->
          <div>
            <div class="text-xs text-gray-400 mb-1">Bybit MT5可用资产</div>
            <div class="text-base font-mono font-bold">
              {{ formatNumber(bybitAssets) }} USDT
            </div>
          </div>
        </div>
      </div>

      <!-- Configuration Area -->
      <div class="bg-[#252930] rounded p-3 space-y-3">
        <div class="text-xs font-bold mb-2">策略配置</div>

        <!-- M Coin Setting -->
        <div>
          <label class="text-xs text-gray-400 mb-1 block">M币设置</label>
          <input
            v-model.number="config.mCoin"
            type="number"
            step="1"
            class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
          />
        </div>

        <!-- Opening/Closing Position Toggles -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-400 mb-1 block">开仓控制</label>
            <button
              @click="config.openingEnabled = !config.openingEnabled"
              :class="[
                'w-full px-3 py-2 rounded text-xs font-bold transition-all',
                config.openingEnabled
                  ? 'bg-[#0ecb81] text-white'
                  : 'bg-[#f6465d] text-white'
              ]"
            >
              {{ config.openingEnabled ? '启用开仓' : '停用开仓' }}
            </button>
          </div>

          <div>
            <label class="text-xs text-gray-400 mb-1 block">平仓控制</label>
            <button
              @click="config.closingEnabled = !config.closingEnabled"
              :class="[
                'w-full px-3 py-2 rounded text-xs font-bold transition-all',
                config.closingEnabled
                  ? 'bg-[#0ecb81] text-white'
                  : 'bg-[#f6465d] text-white'
              ]"
            >
              {{ config.closingEnabled ? '启用平仓' : '停用平仓' }}
            </button>
          </div>
        </div>

        <!-- Data Sync Quantities -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-400 mb-1 block">开仓数据同步数量</label>
            <input
              v-model.number="config.openingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label class="text-xs text-gray-400 mb-1 block">平仓数据同步数量</label>
            <input
              v-model.number="config.closingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1.5 text-sm focus:border-[#f0b90b] focus:outline-none"
            />
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveConfig"
          class="w-full px-4 py-2 bg-[#f0b90b] text-[#1a1d21] rounded font-bold hover:bg-[#e0a800] transition-colors"
        >
          保存配置
        </button>
      </div>

      <!-- Ladder Configuration -->
      <div class="bg-[#252930] rounded p-3">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs font-bold">阶梯配置（最多5级）</span>
          <button
            @click="addLadder"
            :disabled="config.ladders.length >= 5"
            :class="[
              'px-3 py-1 rounded text-xs font-bold transition-colors',
              config.ladders.length >= 5
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-[#f0b90b] text-[#1a1d21] hover:bg-[#e0a800]'
            ]"
          >
            + 添加阶梯
          </button>
        </div>

        <div class="space-y-2">
          <div
            v-for="(ladder, index) in config.ladders"
            :key="index"
            class="bg-[#1a1d21] rounded p-2"
          >
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs text-gray-400">阶梯 {{ index + 1 }}</span>
              <div class="flex items-center space-x-2">
                <label class="flex items-center space-x-1 cursor-pointer">
                  <input
                    v-model="ladder.enabled"
                    type="checkbox"
                    class="w-4 h-4 rounded border-[#2b3139] bg-[#252930] text-[#0ecb81] focus:ring-[#0ecb81]"
                  />
                  <span class="text-xs">启用</span>
                </label>
                <button
                  @click="removeLadder(index)"
                  class="px-2 py-1 bg-[#f6465d] text-white rounded text-xs hover:bg-[#e03d52] transition-colors"
                >
                  删除
                </button>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-2">
              <div>
                <label class="text-xs text-gray-400 mb-1 block">开仓价</label>
                <input
                  v-model.number="ladder.openPrice"
                  type="number"
                  step="0.1"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label class="text-xs text-gray-400 mb-1 block">阈值</label>
                <input
                  v-model.number="ladder.threshold"
                  type="number"
                  step="0.1"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label class="text-xs text-gray-400 mb-1 block">下单数量限制</label>
                <input
                  v-model.number="ladder.qtyLimit"
                  type="number"
                  step="0.01"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Save Strategy Button -->
        <button
          @click="saveStrategy"
          class="w-full mt-3 px-4 py-2 bg-[#f0b90b] text-[#1a1d21] rounded font-bold hover:bg-[#e0a800] transition-colors"
        >
          保存策略
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'

const props = defineProps({
  type: {
    type: String,
    required: true,
    validator: (value) => ['forward', 'reverse'].includes(value)
  }
})

const marketStore = useMarketStore()
const currentSpread = ref(0)
const binanceAssets = ref(10000)
const bybitAssets = ref(8500)

const config = ref({
  mCoin: 100,
  openingEnabled: true,
  closingEnabled: true,
  openingSyncQty: 3,
  closingSyncQty: 3,
  ladders: [
    { enabled: true, openPrice: 2650, threshold: 2.0, qtyLimit: 0.1 },
    { enabled: true, openPrice: 2652, threshold: 3.0, qtyLimit: 0.15 },
    { enabled: false, openPrice: 2654, threshold: 4.0, qtyLimit: 0.2 },
  ]
})

let updateInterval = null

onMounted(() => {
  fetchStrategyData()
  updateInterval = setInterval(fetchStrategyData, 5000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchStrategyData() {
  try {
    const token = localStorage.getItem('token')

    // Fetch market data for spread calculation
    const data = await marketStore.fetchMarketData()

    if (data) {
      // Calculate spread based on strategy type
      // 做多Binance点差 (Forward, Green) = Bybit ASK - Binance BID
      // 做多Bybit点差 (Reverse, Red) = Binance ASK - Bybit BID
      if (props.type === 'forward') {
        // Forward strategy: 做多Binance
        currentSpread.value = data.bybit_ask - data.binance_bid
      } else {
        // Reverse strategy: 做多Bybit
        currentSpread.value = data.binance_ask - data.bybit_bid
      }
    }

    // Fetch real account asset data
    const accountResponse = await fetch(
      'http://localhost:8000/api/v1/accounts/dashboard/aggregated',
      {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      }
    )

    if (accountResponse.ok) {
      const accountData = await accountResponse.json()

      // Calculate available assets for each platform
      const binanceAccounts = accountData.accounts?.filter(acc => acc.platform_id === 1) || []
      const bybitAccounts = accountData.accounts?.filter(acc => acc.platform_id === 2) || []

      binanceAssets.value = binanceAccounts.reduce((sum, acc) =>
        sum + (acc.balance?.available_balance || 0), 0)
      bybitAssets.value = bybitAccounts.reduce((sum, acc) =>
        sum + (acc.balance?.available_balance || 0), 0)
    }
  } catch (error) {
    console.error('Failed to fetch strategy data:', error)
  }
}

function addLadder() {
  if (config.value.ladders.length < 5) {
    config.value.ladders.push({
      enabled: true,
      openPrice: 0,
      threshold: 0,
      qtyLimit: 0
    })
  }
}

function removeLadder(index) {
  config.value.ladders.splice(index, 1)
}

async function saveConfig() {
  try {
    const token = localStorage.getItem('token')

    // Ensure sync quantities are integers
    const configData = {
      strategy_type: props.type,
      opening_sync_count: Math.floor(config.value.openingSyncQty),
      closing_sync_count: Math.floor(config.value.closingSyncQty),
      m_coin: config.value.mCoin,
      opening_enabled: config.value.openingEnabled,
      closing_enabled: config.value.closingEnabled
    }

    const response = await fetch(
      'http://localhost:8000/api/v1/strategies/config',
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(configData)
      }
    )

    if (response.ok) {
      alert('配置保存成功！')
    } else {
      const error = await response.json()
      alert(`配置保存失败: ${error.detail || '未知错误'}`)
    }
  } catch (error) {
    console.error('Failed to save config:', error)
    alert('配置保存失败，请检查网络连接')
  }
}

function saveStrategy() {
  console.log('Saving strategy:', props.type, config.value)
  // API call to save strategy
}

function formatNumber(num) {
  return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
</script>
