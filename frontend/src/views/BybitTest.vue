<template>
  <div class="bybit-test-container">
    <h1>🔷 Bybit API 测试</h1>

    <div class="info-banner">
      <strong>📊 当前显示:</strong> Bybit 完整账户数据 (Unified Trading + MT5)<br>
      <strong>ℹ️ 说明:</strong> 整合统一交易账户和MT5账户的完整数据
    </div>

    <button
      class="test-button"
      @click="testBybitAPI"
      :disabled="loading"
    >
      {{ loading ? '测试中...' : '开始测试' }}
    </button>

    <div v-if="loading" class="loading">
      正在测试 Bybit API...
    </div>

    <div v-if="errorMessage" class="error-message">
      <strong>测试失败:</strong> {{ errorMessage }}
    </div>

    <div v-if="hasErrors && !loading" class="error-message">
      <strong>部分接口调用失败:</strong><br>
      <div v-for="(error, key) in errors" :key="key">
        {{ key }}: {{ getBanInfo(error) || error }}
      </div>
    </div>

    <div v-if="!hasErrors && accountData && !loading" class="success-message">
      <strong>✓ 所有接口调用成功!</strong>
    </div>

    <div v-if="accountData" class="account-card">
      <div class="account-header">
        <div class="account-name">Bybit 完整账户 (Unified Trading + MT5)</div>
        <div class="account-platform">Bybit V5 + MT5</div>
      </div>

      <div class="metrics-grid">
        <div class="metric-item">
          <div class="metric-label">账户总资产</div>
          <div class="metric-value">{{ metrics.totalAssets }} USDT</div>
          <div class="endpoint-info">Unified + MT5 → totalEquity</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">净资产</div>
          <div class="metric-value">{{ metrics.netAssets }} USDT</div>
          <div class="endpoint-info">Unified + MT5 → totalWalletBalance</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">可用总资产</div>
          <div class="metric-value">{{ metrics.availableBalance }} USDT</div>
          <div class="endpoint-info">Unified + MT5 → totalAvailableBalance</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">冻结资产</div>
          <div class="metric-value">{{ metrics.frozenAssets }} USDT</div>
          <div class="endpoint-info">Unified → totalInitialMargin</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">总持仓</div>
          <div class="metric-value">{{ metrics.totalPositions }} USDT</div>
          <div class="endpoint-info">/v5/position/list?settleCoin=USDT → Σ(size×markPrice)</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">当日盈亏</div>
          <div
            class="metric-value"
            :class="getValueClass(metrics.dailyPnl)"
          >
            {{ metrics.dailyPnl }} USDT
          </div>
          <div class="endpoint-info">/v5/position/closed-pnl?settleCoin=USDT → closedPnl + unrealizedPnl</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">保证金余额</div>
          <div class="metric-value">{{ metrics.marginBalance }} USDT</div>
          <div class="endpoint-info">/v5/account/wallet-balance?coin=USDT → totalMarginBalance</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">风险率</div>
          <div
            class="metric-value"
            :class="getRiskClass(metrics.riskRatio)"
          >
            {{ metrics.riskRatio }}
          </div>
          <div class="endpoint-info">/v5/account/wallet-balance?coin=USDT → (totalMaintenanceMargin / totalMarginBalance) × 100</div>
        </div>

        <div class="metric-item">
          <div class="metric-label">资金费</div>
          <div
            class="metric-value"
            :class="getValueClass(metrics.fundingFee)"
          >
            {{ metrics.fundingFee }} USDT
          </div>
          <div class="endpoint-info">/v5/account/funding-fee?settleCoin=USDT → Σ(fundingFee)</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import CryptoJS from 'crypto-js'

const API_KEY = 'KWL699v3EhZBVxzKOg'
const API_SECRET = 'EiOw3inPLTVFrTmi0s2zEtTztWmuKfqGvSUg'
const BASE_URL = 'https://api.bybit.com'

const loading = ref(false)
const errorMessage = ref('')
const accountData = ref(null)
const errors = ref({})

const hasErrors = computed(() => Object.keys(errors.value).length > 0)

const metrics = ref({
  totalAssets: '暂无',
  availableBalance: '暂无',
  netAssets: '暂无',
  frozenAssets: '暂无',
  totalPositions: '暂无',
  dailyPnl: '暂无',
  marginBalance: '暂无',
  riskRatio: '暂无',
  fundingFee: '暂无'
})

function generateSignature(timestamp, params) {
  const recvWindow = '5000'
  const paramStr = Object.keys(params)
    .sort()
    .map(key => `${key}=${params[key]}`)
    .join('&')

  const signStr = timestamp + API_KEY + recvWindow + paramStr
  return CryptoJS.HmacSHA256(signStr, API_SECRET).toString()
}

async function makeBybitRequest(endpoint, params = {}) {
  const timestamp = Date.now().toString()

  // Ensure all parameter values are strings
  const stringParams = {}
  Object.keys(params).forEach(key => {
    stringParams[key] = String(params[key])
  })

  const signature = generateSignature(timestamp, stringParams)

  const queryString = Object.keys(stringParams)
    .sort()
    .map(key => `${key}=${encodeURIComponent(stringParams[key])}`)
    .join('&')

  const url = `${BASE_URL}${endpoint}${queryString ? '?' + queryString : ''}`

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'X-BAPI-API-KEY': API_KEY,
      'X-BAPI-TIMESTAMP': timestamp,
      'X-BAPI-SIGN': signature,
      'X-BAPI-RECV-WINDOW': '5000'
    }
  })

  // Check if response has content
  const text = await response.text()
  if (!text) {
    throw new Error('Empty response from API')
  }

  const data = JSON.parse(text)

  if (data.retCode !== 0) {
    throw new Error(data.retMsg || 'API Error')
  }

  return data.result
}

function formatNumber(num) {
  if (num === null || num === undefined) return '暂无'
  return parseFloat(num).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })
}

function getBanInfo(error) {
  if (!error) return null

  if (error.toLowerCase().includes('rate limit') || error.toLowerCase().includes('banned')) {
    const match = error.match(/(\d{13})/)
    if (match) {
      const banUntilMs = parseInt(match[1])
      const banUntilDate = new Date(banUntilMs)
      const now = new Date()
      const minutesLeft = Math.ceil((banUntilDate - now) / 1000 / 60)

      if (minutesLeft > 0) {
        const hours = banUntilDate.getHours()
        const minutes = banUntilDate.getMinutes()
        const ampm = hours >= 12 ? 'PM' : 'AM'
        const displayHours = hours % 12 || 12
        const displayMinutes = minutes.toString().padStart(2, '0')

        return `限制至${displayHours}:${displayMinutes} ${ampm} (${minutesLeft}分钟)`
      }
    }
    return '暂时受限'
  }

  return null
}

function getValueClass(value) {
  const numValue = parseFloat(value.replace(/,/g, ''))
  if (isNaN(numValue)) return ''
  return numValue >= 0 ? 'positive' : 'negative'
}

function getRiskClass(value) {
  const numValue = parseFloat(value)
  if (isNaN(numValue)) return ''
  return numValue > 60 ? 'warning' : ''
}

async function testBybitAPI() {
  loading.value = true
  errorMessage.value = ''
  errors.value = {}
  accountData.value = null

  try {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const startTime = today.getTime()
    const endTime = Date.now()

    const data = {
      unifiedBalance: null,
      mt5Balance: null,
      positions: null,
      profitLoss: null,
      fundingFee: null
    }

    // 1. Get Unified account balance
    try {
      data.unifiedBalance = await makeBybitRequest('/v5/account/wallet-balance', {
        accountType: 'UNIFIED',
        coin: 'USDT'
      })
    } catch (error) {
      errors.value.unifiedBalance = error.message
    }

    // 2. Get MT5 account balance (via backend API)
    try {
      const response = await fetch('http://13.115.21.77:8000/api/v1/test/mt5-balance')
      if (response.ok) {
        data.mt5Balance = await response.json()
      } else {
        throw new Error('MT5 API call failed')
      }
    } catch (error) {
      errors.value.mt5Balance = error.message
    }

    // 3. Get positions
    try {
      data.positions = await makeBybitRequest('/v5/position/list', {
        category: 'linear',
        settleCoin: 'USDT'
      })
    } catch (error) {
      errors.value.positions = error.message
    }

    // 4. Get profit/loss
    try {
      data.profitLoss = await makeBybitRequest('/v5/position/closed-pnl', {
        category: 'linear',
        settleCoin: 'USDT',
        startTime: startTime,
        endTime: endTime,
        limit: 50
      })
    } catch (error) {
      errors.value.profitLoss = error.message
    }

    // 4. Get funding fee
    try {
      data.fundingFee = await makeBybitRequest('/v5/account/funding-fee', {
        category: 'linear',
        settleCoin: 'USDT',
        startTime: startTime,
        endTime: endTime,
        limit: 50
      })
    } catch (error) {
      // Empty response is expected for accounts with no funding fee history
      if (error.message === 'Empty response from API') {
        data.fundingFee = { list: [] }  // Set empty list instead of error
      } else {
        errors.value.fundingFee = error.message
      }
    }

    accountData.value = data
    calculateMetrics(data)

  } catch (error) {
    errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}

function calculateMetrics(data) {
  const newMetrics = {
    totalAssets: '暂无',
    availableBalance: '暂无',
    netAssets: '暂无',
    frozenAssets: '暂无',
    totalPositions: '暂无',
    dailyPnl: '暂无',
    marginBalance: '暂无',
    riskRatio: '暂无',
    fundingFee: '暂无'
  }

  // Initialize totals
  let totalEquity = 0
  let totalWalletBalance = 0
  let totalMarginBalance = 0
  let totalAvailableBalance = 0
  let totalInitialMargin = 0
  let totalMaintenanceMargin = 0

  // 1. Unified Account metrics
  if (data.unifiedBalance && data.unifiedBalance.list && data.unifiedBalance.list.length > 0) {
    const unifiedAccount = data.unifiedBalance.list[0]
    const unifiedEquity = parseFloat(unifiedAccount.totalEquity || 0)
    const unifiedWallet = parseFloat(unifiedAccount.totalWalletBalance || 0)
    const unifiedMargin = parseFloat(unifiedAccount.totalMarginBalance || 0)
    const unifiedAvailable = parseFloat(unifiedAccount.totalAvailableBalance || 0)
    const unifiedInitialMargin = parseFloat(unifiedAccount.totalInitialMargin || 0)
    const unifiedMaintenanceMargin = parseFloat(unifiedAccount.totalMaintenanceMargin || 0)

    totalEquity += unifiedEquity
    totalWalletBalance += unifiedWallet
    totalMarginBalance += unifiedMargin
    totalAvailableBalance += unifiedAvailable
    totalInitialMargin += unifiedInitialMargin
    totalMaintenanceMargin += unifiedMaintenanceMargin
  }

  // 2. MT5 Account metrics
  if (data.mt5Balance && !data.mt5Balance.error) {
    const mt5Balance = parseFloat(data.mt5Balance.balance || 0)
    const mt5Equity = parseFloat(data.mt5Balance.equity || 0)
    const mt5FreeMargin = parseFloat(data.mt5Balance.margin_free || 0)

    totalEquity += mt5Equity
    totalWalletBalance += mt5Balance
    totalAvailableBalance += mt5FreeMargin
  }

  // Set combined metrics
  newMetrics.totalAssets = formatNumber(totalEquity)
  newMetrics.netAssets = formatNumber(totalWalletBalance)
  newMetrics.availableBalance = formatNumber(totalAvailableBalance)
  newMetrics.frozenAssets = formatNumber(totalInitialMargin)
  newMetrics.marginBalance = formatNumber(totalMarginBalance)

  // Calculate risk ratio
  const riskRatio = totalMarginBalance > 0 ? (totalMaintenanceMargin / totalMarginBalance * 100) : 0
  newMetrics.riskRatio = riskRatio.toFixed(2) + '%'

  // Positions metrics
  if (data.positions && data.positions.list) {
    let totalPositionValue = 0
    let totalUnrealizedPnl = 0

    data.positions.list.forEach(pos => {
      const size = parseFloat(pos.size || 0)
      const markPrice = parseFloat(pos.markPrice || 0)
      const unrealizedPnl = parseFloat(pos.unrealisedPnl || 0)

      totalPositionValue += Math.abs(size * markPrice)
      totalUnrealizedPnl += unrealizedPnl
    })

    newMetrics.totalPositions = formatNumber(totalPositionValue)

    // Calculate daily P&L
    let closedPnl = 0
    if (data.profitLoss && data.profitLoss.list) {
      data.profitLoss.list.forEach(pnl => {
        closedPnl += parseFloat(pnl.closedPnl || 0)
      })
    }

    const dailyPnl = closedPnl + totalUnrealizedPnl
    newMetrics.dailyPnl = formatNumber(dailyPnl)
  }

  // Funding fee
  if (data.fundingFee && data.fundingFee.list) {
    let totalFundingFee = 0
    data.fundingFee.list.forEach(fee => {
      totalFundingFee += parseFloat(fee.fundingFee || 0)
    })
    newMetrics.fundingFee = formatNumber(totalFundingFee)
  }

  metrics.value = newMetrics
}
</script>

<style scoped>
.bybit-test-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
  padding: 20px;
}

.info-banner {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: 2px solid #a78bfa;
  border-radius: 12px;
  padding: 15px 20px;
  margin: 0 auto 20px;
  max-width: 1200px;
  color: white;
  font-size: 14px;
  line-height: 1.6;
  box-shadow: 0 4px 15px rgba(0,0,0,0.2);
}

h1 {
  color: white;
  text-align: center;
  margin-bottom: 30px;
  font-size: 2.5em;
  text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
}

.test-button {
  display: block;
  width: 200px;
  margin: 0 auto 30px;
  padding: 15px 30px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 25px;
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  box-shadow: 0 4px 15px rgba(0,0,0,0.2);
}

.test-button:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0,0,0,0.3);
}

.test-button:active:not(:disabled) {
  transform: translateY(0);
}

.test-button:disabled {
  background: #666;
  cursor: not-allowed;
  transform: none;
}

.loading {
  text-align: center;
  color: white;
  font-size: 18px;
  margin: 20px 0;
}

.error-message {
  background: #fee2e2;
  border: 1px solid #ef4444;
  color: #991b1b;
  padding: 15px;
  border-radius: 10px;
  margin: 0 auto 20px;
  max-width: 1200px;
}

.success-message {
  background: #d1fae5;
  border: 1px solid #10b981;
  color: #065f46;
  padding: 15px;
  border-radius: 10px;
  margin: 0 auto 20px;
  max-width: 1200px;
}

.account-card {
  background: white;
  border-radius: 15px;
  padding: 25px;
  margin: 0 auto;
  max-width: 1200px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}

.account-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 2px solid #f0f0f0;
}

.account-name {
  font-size: 24px;
  font-weight: bold;
  color: #333;
}

.account-platform {
  padding: 5px 15px;
  background: #fbbf24;
  color: white;
  border-radius: 20px;
  font-size: 14px;
  font-weight: bold;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 15px;
}

.metric-item {
  padding: 15px;
  background: #f8f9fa;
  border-radius: 10px;
  border-left: 4px solid #667eea;
}

.metric-label {
  font-size: 14px;
  color: #666;
  margin-bottom: 5px;
}

.metric-value {
  font-size: 20px;
  font-weight: bold;
  color: #333;
}

.metric-value.positive {
  color: #10b981;
}

.metric-value.negative {
  color: #ef4444;
}

.metric-value.warning {
  color: #f59e0b;
}

.endpoint-info {
  background: #e0e7ff;
  padding: 10px 15px;
  border-radius: 8px;
  margin-top: 10px;
  font-size: 12px;
  color: #4338ca;
  font-family: 'Courier New', monospace;
}
</style>
