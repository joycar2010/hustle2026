<template>
  <div class="h-full flex flex-col">
    <!-- Total Profit and Fees Header -->
    <div class="p-2 md:p-3 bg-[#252930] border-b border-[#2b3139]">
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 md:gap-3 mb-2 md:mb-3">
        <!-- Left: Bybit Fees -->
        <div class="bg-[#1e2329] rounded p-2 sm:order-1 order-2">
          <div class="text-xs text-gray-400 mb-1 text-center">Bybit 掉期费</div>
          <div class="flex flex-col space-y-1">
            <div class="flex justify-between text-xs">
              <span class="text-gray-400">做多:</span>
              <span class="font-mono" :class="bybitLongSwapFee >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                {{ bybitLongSwapFee >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(bybitLongSwapFee)) }}
              </span>
            </div>
            <div class="flex justify-between text-xs">
              <span class="text-gray-400">做空:</span>
              <span class="font-mono" :class="bybitShortSwapFee >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                {{ bybitShortSwapFee >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(bybitShortSwapFee)) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Center: Total Profit -->
        <div class="bg-[#1e2329] rounded p-2 flex flex-col items-center justify-center sm:order-2 order-first">
          <div class="text-xs text-gray-400 mb-1">总盈利</div>
          <div class="text-lg md:text-xl font-bold font-mono" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }}
          </div>
          <div class="text-xs text-gray-400">USDT</div>
        </div>

        <!-- Right: Binance Fees -->
        <div class="bg-[#1e2329] rounded p-2 sm:order-3 order-3">
          <div class="text-xs text-gray-400 mb-1 text-center">Binance 资金费</div>
          <div class="flex flex-col space-y-1">
            <div class="flex justify-between text-xs">
              <span class="text-gray-400">做多:</span>
              <span class="font-mono" :class="binanceLongFundingRate >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                {{ binanceLongFundingRate >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(binanceLongFundingRate)) }}
              </span>
            </div>
            <div class="flex justify-between text-xs">
              <span class="text-gray-400">做空:</span>
              <span class="font-mono" :class="binanceShortFundingRate >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                {{ binanceShortFundingRate >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(binanceShortFundingRate)) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Arbitrage Strategy Position Data -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <!-- Reverse Arbitrage -->
        <div class="bg-[#1e2329] rounded p-2">
          <div class="text-xs text-gray-400 mb-1">反向持仓 (Bybit MT5)</div>
          <div class="flex justify-center text-xs">
            <div class="flex items-center space-x-2">
              <span class="text-gray-400">实际持仓:</span>
              <span class="font-mono text-white text-lg">{{ reverseActualPosition.toFixed(2) }}</span>
            </div>
          </div>
        </div>

        <!-- Forward Arbitrage -->
        <div class="bg-[#1e2329] rounded p-2">
          <div class="text-xs text-gray-400 mb-1">正向持仓 (Binance)</div>
          <div class="flex justify-center text-xs">
            <div class="flex items-center space-x-2">
              <span class="text-gray-400">实际持仓:</span>
              <span class="font-mono text-white text-lg">{{ forwardActualPosition.toFixed(2) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-2 md:p-3">
      <div class="grid grid-cols-1 gap-2 md:gap-3 h-full">
      <!-- Bybit MT5 Card -->
      <div class="bg-[#252930] rounded p-3 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <div class="w-7 h-7 bg-[#ff9800] rounded flex items-center justify-center">
              <span class="text-white font-bold text-lg">B</span>
            </div>
            <div>
              <div class="font-medium text-lg">Bybit MT5 <span class="text-sm text-gray-400">XAUUSD.s</span></div>
            </div>
          </div>
          <div :class="['w-3 h-3 rounded-full', bybitConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Compact) -->
        <div class="mb-2 text-center py-1.5 bg-[#1e2329] rounded">
          <div class="text-sm text-gray-400 mb-0.5">实时价格</div>
          <div :class="['text-2xl font-mono font-bold', getPriceClass(bybit.mid, bybit.prevMid)]">
            {{ formatPrice(bybit.mid) }}
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-2 mb-2">
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">ASK</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">BID</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-sm text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 h-3 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-sm font-mono">{{ bybitLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Binance Card -->
      <div class="bg-[#252930] rounded p-3 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-2">
            <div class="w-7 h-7 bg-[#f0b90b] rounded flex items-center justify-center">
              <span class="text-[#1a1d21] font-bold text-lg">B</span>
            </div>
            <div>
              <div class="font-medium text-lg">Binance <span class="text-sm text-gray-400">XAUUSDT</span></div>
            </div>
          </div>
          <div :class="['w-3 h-3 rounded-full', binanceConnected ? 'bg-[#0ecb81] animate-pulse' : 'bg-[#f6465d]']"></div>
        </div>

        <!-- Real-time Price (Compact) -->
        <div class="mb-2 text-center py-1.5 bg-[#1e2329] rounded">
          <div class="text-sm text-gray-400 mb-0.5">实时价格</div>
          <div :class="['text-2xl font-mono font-bold', getPriceClass(binance.mid, binance.prevMid)]">
            {{ formatPrice(binance.mid) }}
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-2 mb-2">
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">ASK</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-2 py-1.5 border border-[#2b3139]">
            <div class="text-sm text-gray-400 mb-0.5">BID</div>
            <div :class="['text-lg font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-1.5 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-sm text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-1 h-3 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span class="text-sm font-mono">{{ binanceLagCount }}</span>
          </div>
        </div>
      </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

const marketStore = useMarketStore()

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })
const binance = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })

const bybitLagCount = ref(0)
const binanceLagCount = ref(0)
let lastUpdateTime = Date.now()
let lagTimer = null

// Profit and position data
const totalProfit = ref(0)
const forwardActualPosition = ref(0)
const reverseActualPosition = ref(0)

// Fee data
const bybitLongSwapFee = ref(0)
const bybitShortSwapFee = ref(0)
const binanceLongFundingRate = ref(0)
const binanceShortFundingRate = ref(0)

const bybitLagLevel = computed(() => Math.min(Math.floor(bybitLagCount.value / 10), 5))
const binanceLagLevel = computed(() => Math.min(Math.floor(binanceLagCount.value / 10), 5))

watch(() => marketStore.marketData, (data) => {
  if (!data) return
  const now = Date.now()
  if (now - lastUpdateTime > 2000) {
    bybitLagCount.value++
    binanceLagCount.value++
  }
  lastUpdateTime = now

  bybit.value.prevBid = bybit.value.bid
  bybit.value.prevAsk = bybit.value.ask
  bybit.value.prevMid = bybit.value.mid
  binance.value.prevBid = binance.value.bid
  binance.value.prevAsk = binance.value.ask
  binance.value.prevMid = binance.value.mid

  bybit.value.bid = data.bybit_bid || 0
  bybit.value.ask = data.bybit_ask || 0
  bybit.value.mid = data.bybit_mid || ((bybit.value.bid + bybit.value.ask) / 2)

  binance.value.bid = data.binance_bid || 0
  binance.value.ask = data.binance_ask || 0
  binance.value.mid = data.binance_mid || ((binance.value.bid + binance.value.ask) / 2)

  bybitConnected.value = true
  binanceConnected.value = true
})

watch(() => marketStore.connected, (val) => {
  if (!val) {
    bybitConnected.value = false
    binanceConnected.value = false
  }
})

// Watch for account balance updates via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (message && message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  }
})

function handleAccountBalanceUpdate(data) {
  // Debug: log received data
  console.log('[MarketCards] Received account_balance data:', {
    accounts: data.accounts?.length || 0,
    positions: data.positions?.length || 0,
    positionsDetail: data.positions
  })

  // Update total profit
  if (data.summary) {
    totalProfit.value = data.summary.daily_pnl || 0
  }

  // Extract fee data from accounts
  if (data.accounts && data.accounts.length > 0) {
    // Reset fee values
    bybitLongSwapFee.value = 0
    bybitShortSwapFee.value = 0
    binanceLongFundingRate.value = 0
    binanceShortFundingRate.value = 0

    // Aggregate fees from all accounts
    data.accounts.forEach(account => {
      if (account.platform_id === 2) {
        // Bybit accounts
        bybitLongSwapFee.value += account.balance?.long_swap_fee || 0
        bybitShortSwapFee.value += account.balance?.short_swap_fee || 0
      } else if (account.platform_id === 1) {
        // Binance accounts
        binanceLongFundingRate.value += account.balance?.long_funding_rate || 0
        binanceShortFundingRate.value += account.balance?.short_funding_rate || 0
      }
    })
  }

  // Extract actual positions from positions array
  if (data.positions && data.positions.length > 0) {
    // Reset position values
    forwardActualPosition.value = 0
    reverseActualPosition.value = 0

    // Aggregate positions by platform
    data.positions.forEach(position => {
      // Find the account for this position to get platform_id
      const account = data.accounts?.find(acc => acc.account_id === position.account_id)
      if (!account) {
        console.warn('[MarketCards] Position without matching account:', position)
        return
      }

      console.log('[MarketCards] Processing position:', {
        symbol: position.symbol,
        side: position.side,
        size: position.size,
        platform_id: account.platform_id,
        account_name: account.account_name
      })

      // For Bybit MT5: Sell (short) positions = reverse arbitrage
      // For Binance: Buy (long) positions = forward arbitrage
      if (account.platform_id === 2) {
        // Bybit MT5: count all positions (both Buy and Sell)
        // Reverse arbitrage uses Bybit short positions
        if (position.side === 'Sell') {
          reverseActualPosition.value += Math.abs(position.size || 0)
          console.log('[MarketCards] Added to reverse position:', position.size, 'Total:', reverseActualPosition.value)
        }
      } else if (account.platform_id === 1) {
        // Binance: count Buy (long) positions for forward arbitrage
        if (position.side === 'Buy') {
          forwardActualPosition.value += Math.abs(position.size || 0)
          console.log('[MarketCards] Added to forward position:', position.size, 'Total:', forwardActualPosition.value)
        }
      }
    })

    console.log('[MarketCards] Final positions:', {
      reverse: reverseActualPosition.value,
      forward: forwardActualPosition.value
    })
  } else {
    // No positions, reset to 0
    forwardActualPosition.value = 0
    reverseActualPosition.value = 0
    console.log('[MarketCards] No positions in data')
  }
}

onMounted(() => {
  marketStore.connect()
  lagTimer = setInterval(() => {
    if (Date.now() - lastUpdateTime > 2000) {
      bybitLagCount.value++
      binanceLagCount.value++
    }
  }, 2000)

  // Initial fetch
  fetchAccountData()
})

onUnmounted(() => {
  if (lagTimer) clearInterval(lagTimer)
})

function formatPrice(price) {
  return price ? price.toFixed(2) : '0.00'
}

function getPriceClass(current, previous) {
  if (!previous || current === previous) return 'text-white'
  return current > previous ? 'text-[#0ecb81]' : 'text-[#f6465d]'
}

function formatNumber(num) {
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data
    if (data.summary) {
      totalProfit.value = data.summary.daily_pnl || 0
    }

    // Extract fee data from accounts
    if (data.accounts && data.accounts.length > 0) {
      // Reset fee values
      bybitLongSwapFee.value = 0
      bybitShortSwapFee.value = 0
      binanceLongFundingRate.value = 0
      binanceShortFundingRate.value = 0

      // Aggregate fees from all accounts
      data.accounts.forEach(account => {
        if (account.platform_id === 2) {
          // Bybit accounts
          bybitLongSwapFee.value += account.balance?.long_swap_fee || 0
          bybitShortSwapFee.value += account.balance?.short_swap_fee || 0
        } else if (account.platform_id === 1) {
          // Binance accounts
          binanceLongFundingRate.value += account.balance?.long_funding_rate || 0
          binanceShortFundingRate.value += account.balance?.short_funding_rate || 0
        }
      })
    }

    // Extract actual positions from positions array
    if (data.positions && data.positions.length > 0) {
      // Reset position values
      forwardActualPosition.value = 0
      reverseActualPosition.value = 0

      // Aggregate positions by platform
      data.positions.forEach(position => {
        // Find the account for this position to get platform_id
        const account = data.accounts?.find(acc => acc.account_id === position.account_id)
        if (!account) return

        // For Bybit MT5: Sell (short) positions = reverse arbitrage
        // For Binance: Buy (long) positions = forward arbitrage
        if (account.platform_id === 2) {
          // Bybit MT5: count all positions (both Buy and Sell)
          // Reverse arbitrage uses Bybit short positions
          if (position.side === 'Sell') {
            reverseActualPosition.value += Math.abs(position.size || 0)
          }
        } else if (account.platform_id === 1) {
          // Binance: count Buy (long) positions for forward arbitrage
          if (position.side === 'Buy') {
            forwardActualPosition.value += Math.abs(position.size || 0)
          }
        }
      })
    } else {
      // No positions, reset to 0
      forwardActualPosition.value = 0
      reverseActualPosition.value = 0
    }
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}
</script>
