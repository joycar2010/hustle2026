<template>
  <div class="h-full flex flex-col p-3">
    <h3 class="text-sm font-bold mb-3">保证金风险仪表盘</h3>
    <div class="space-y-3">
      <!-- Margin Rate Card -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs text-gray-400 mb-2">保证金率</div>
        <div class="flex items-center justify-between mb-2">
          <span class="text-2xl font-bold font-mono">{{ riskData.marginRate }}%</span>
          <span :class="['text-sm font-bold', getRiskColor(riskData.marginRate)]">
            {{ getRiskLevel(riskData.marginRate) }}
          </span>
        </div>
        <div class="w-full bg-[#1a1d21] rounded-full h-2">
          <div
            :class="['h-2 rounded-full transition-all', getRiskBarColor(riskData.marginRate)]"
            :style="{ width: `${Math.min(riskData.marginRate, 100)}%` }"
          ></div>
        </div>
      </div>

      <!-- Risk Rate Card -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs text-gray-400 mb-2">风险率</div>
        <div class="flex items-center justify-between mb-2">
          <span class="text-2xl font-bold font-mono">{{ riskData.riskRate }}%</span>
          <span :class="['text-sm font-bold', getRiskColor(riskData.riskRate)]">
            {{ getRiskLevel(riskData.riskRate) }}
          </span>
        </div>
        <div class="w-full bg-[#1a1d21] rounded-full h-2">
          <div
            :class="['h-2 rounded-full transition-all', getRiskBarColor(riskData.riskRate)]"
            :style="{ width: `${Math.min(riskData.riskRate, 100)}%` }"
          ></div>
        </div>
      </div>

      <!-- Account Equity Card -->
      <div class="bg-[#252930] rounded p-3">
        <div class="text-xs text-gray-400 mb-2">账户权益</div>
        <div class="space-y-2">
          <div class="flex justify-between items-center">
            <span class="text-xs text-gray-400">Binance</span>
            <span class="text-base font-mono font-bold">
              {{ formatNumber(riskData.binanceEquity) }} USDT
            </span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-xs text-gray-400">Bybit MT5</span>
            <span class="text-base font-mono font-bold">
              {{ formatNumber(riskData.bybitEquity) }} USDT
            </span>
          </div>
          <div class="pt-2 border-t border-[#2b3139] flex justify-between items-center">
            <span class="text-xs font-bold">总权益</span>
            <span class="text-lg font-mono font-bold text-[#f0b90b]">
              {{ formatNumber(riskData.totalEquity) }} USDT
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import api from '@/services/api'

const riskData = ref({
  marginRate: 35,
  riskRate: 42,
  binanceEquity: 10000,
  bybitEquity: 8500,
})

const totalEquity = computed(() => riskData.value.binanceEquity + riskData.value.bybitEquity)

riskData.value.totalEquity = totalEquity.value

let updateInterval = null

onMounted(() => {
  fetchRiskData()
  updateInterval = setInterval(fetchRiskData, 5000)
})

onUnmounted(() => {
  if (updateInterval) {
    clearInterval(updateInterval)
  }
})

async function fetchRiskData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

    // Extract risk data from aggregated account data
    const binanceAccounts = data.accounts?.filter(acc => acc.platform_id === 1) || []
    const bybitAccounts = data.accounts?.filter(acc => acc.platform_id === 2) || []

    // Calculate total equity for each platform
    const binanceEquity = binanceAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.net_assets || 0), 0)
    const bybitEquity = bybitAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.net_assets || 0), 0)

    // Calculate average risk ratio
    const allAccounts = [...binanceAccounts, ...bybitAccounts]
    const accountsWithRisk = allAccounts.filter(acc => acc.balance?.risk_ratio != null)
    const avgRiskRatio = accountsWithRisk.length > 0
      ? accountsWithRisk.reduce((sum, acc) => sum + (acc.balance.risk_ratio || 0), 0) / accountsWithRisk.length
      : 0

    // Calculate margin rate (using available balance / total assets ratio)
    const totalAssets = binanceEquity + bybitEquity
    const totalAvailable = allAccounts.reduce((sum, acc) =>
      sum + (acc.balance?.available_balance || 0), 0)
    const marginRate = totalAssets > 0 ? ((totalAssets - totalAvailable) / totalAssets * 100) : 0

    riskData.value = {
      marginRate: marginRate,
      riskRate: avgRiskRatio,
      binanceEquity: binanceEquity,
      bybitEquity: bybitEquity,
      totalEquity: binanceEquity + bybitEquity
    }
  } catch (error) {
    console.error('Failed to fetch risk data:', error)
  }
}

function getRiskColor(value) {
  if (value < 30) return 'text-[#0ecb81]'
  if (value < 60) return 'text-[#f0b90b]'
  return 'text-[#f6465d]'
}

function getRiskBarColor(value) {
  if (value < 30) return 'bg-[#0ecb81]'
  if (value < 60) return 'bg-[#f0b90b]'
  return 'bg-[#f6465d]'
}

function getRiskLevel(value) {
  if (value < 30) return '安全'
  if (value < 60) return '警告'
  return '危险'
}

function formatNumber(num) {
  return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
</script>
