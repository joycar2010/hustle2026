<template>
  <div class="binance-test-container">
    <div class="container">
      <h1>🔍 Binance API 测试页面</h1>

      <button class="test-button" :disabled="loading" @click="runTest">
        {{ loading ? '测试中...' : '开始测试' }}
      </button>

      <div v-if="loading" class="loading">
        正在测试 Binance API...
      </div>

      <div v-if="results" class="account-card">
        <div class="account-header">
          <div class="account-name">Binance 账户信息</div>
          <div :class="['status-badge', results.hasError ? 'status-error' : 'status-success']">
            {{ results.hasError ? '部分失败' : '正常' }}
          </div>
        </div>

        <!-- API Status Section -->
        <div class="api-status-grid">
          <div v-for="api in apiStatuses" :key="api.name" :class="['api-status-item', api.ok ? 'api-ok' : 'api-fail']">
            <span class="api-name">{{ api.name }}</span>
            <span class="api-value">{{ api.value }}</span>
            <span v-if="!api.ok" class="api-error">{{ api.errorMsg }}</span>
          </div>
        </div>

        <div class="data-grid">
          <div v-for="metric in metrics" :key="metric.label" class="data-item">
            <span class="data-label">{{ metric.label }}</span>
            <span :class="['data-value', getValueClass(metric)]">
              {{ formatValue(metric) }}
            </span>
          </div>
        </div>

        <div v-if="results.error" class="error-message">
          <strong>合约账户错误:</strong> {{ results.error }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import CryptoJS from 'crypto-js'

const API_KEY = 'Ym1OIwyoadLOL6f4GbNOyH52F7P0tllmp5gBjbOiS9nxKtk340QUCt4qTds7dVr2'
const API_SECRET = 'DtM28kn5K5Oi4HAf7WLVV3KLWaUQmZKX3gcsrRdoIlueHbm9aCmMsDxdzFPcns5c'

const loading = ref(false)
const results = ref(null)

const metrics = computed(() => {
  if (!results.value) return []

  return [
    { label: '账户总资产', value: results.value.totalAssets, field: 'totalAssets', data: null },
    { label: '可用总资产', value: results.value.availableBalance, field: 'availableBalance', data: null },
    { label: '净资产', value: results.value.netAssets, field: 'netAssets', data: results.value.futures },
    { label: '总持仓', value: results.value.totalPositions, field: 'totalPositions', data: null },
    { label: '冻结资产', value: results.value.frozenAssets, field: 'frozenAssets', data: null },
    { label: '当日盈亏', value: results.value.dailyPnl, field: 'dailyPnl', data: null },
    { label: '保证金余额', value: results.value.marginBalance, field: 'marginBalance', data: results.value.futures },
    { label: '风险率', value: results.value.riskRatio, field: 'riskRatio', data: results.value.futures },
    { label: '掉期费', value: results.value.fundingFee, field: 'fundingFee', data: null }
  ]
})

const apiStatuses = computed(() => {
  if (!results.value) return []
  const r = results.value

  function fmtUsdt(val) {
    return val != null ? val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' USDT' : '0.00 USDT'
  }

  return [
    {
      name: '现货 Spot',
      ok: !r.spot?.error,
      value: fmtUsdt(r.spotTotal),
      errorMsg: r.spot?.error ? (r.spot.error.msg || JSON.stringify(r.spot.error)) : ''
    },
    {
      name: '杠杆 Margin',
      ok: !r.margin?.error,
      value: fmtUsdt(r.marginTotal),
      errorMsg: r.margin?.error ? (r.margin.error.msg || JSON.stringify(r.margin.error)) : ''
    },
    {
      name: '合约 Futures',
      ok: !r.futures?.error,
      value: fmtUsdt(r.futuresTotal),
      errorMsg: r.futures?.error ? (r.futures.error.msg || JSON.stringify(r.futures.error)) : ''
    },
    {
      name: '期权 Options',
      ok: !r.options?.error,
      value: fmtUsdt(r.optionsTotal),
      errorMsg: r.options?.error ? (r.options.error.msg || JSON.stringify(r.options.error)) : ''
    }
  ]
})

function generateSignature(queryString) {
  return CryptoJS.HmacSHA256(queryString, API_SECRET).toString()
}

function getBanInfo(error) {
  if (!error || !error.msg) return null

  const match = error.msg.match(/banned until (\d+)/)
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

  return null
}

function getValueClass(metric) {
  if (metric.data && metric.data.error) {
    const banInfo = getBanInfo(metric.data.error)
    return banInfo ? 'value-banned' : 'value-unavailable'
  }

  if (metric.value == null) {
    return 'value-unavailable'
  }

  if (['dailyPnl', 'fundingFee'].includes(metric.field)) {
    return metric.value >= 0 ? 'value-positive' : 'value-negative'
  }

  return 'value-neutral'
}

function formatValue(metric) {
  if (metric.data && metric.data.error) {
    const banInfo = getBanInfo(metric.data.error)
    if (banInfo) return banInfo
    return '暂无'
  }

  if (metric.value == null) {
    return '暂无'
  }

  const num = parseFloat(metric.value)
  if (isNaN(num)) {
    return '暂无'
  }

  if (metric.field === 'riskRatio') {
    return num.toFixed(2) + '%'
  }

  const sign = num >= 0 && ['dailyPnl', 'fundingFee'].includes(metric.field) ? '+' : ''
  return `${sign}${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`
}

async function runTest() {
  loading.value = true

  try {
    const [spotData, marginData, futuresData, optionsData, positionsData, dailyPnlData, fundingFeeData] = await Promise.all([
      testSpotAccount(),
      testMarginAccount(),
      testFuturesAccount(),
      testOptionsAccount(),
      testPositionRisk(),
      testDailyPnL(),
      testFundingFees()
    ])

    // Spot USDT balance
    let spotTotal = 0
    let spotFree = 0
    let spotLocked = 0
    if (spotData && !spotData.error && spotData.balances) {
      spotData.balances.forEach(balance => {
        if (balance.asset === 'USDT') {
          spotTotal = parseFloat(balance.free) + parseFloat(balance.locked)
          spotFree = parseFloat(balance.free)
          spotLocked = parseFloat(balance.locked)
        }
      })
    }

    // Cross Margin USDT net asset
    let marginTotal = 0
    let marginFree = 0
    let marginLocked = 0
    if (marginData && !marginData.error && marginData.userAssets) {
      const usdtAsset = marginData.userAssets.find(a => a.asset === 'USDT')
      if (usdtAsset) {
        marginTotal = parseFloat(usdtAsset.netAsset || 0)
        marginFree = parseFloat(usdtAsset.free || 0)
        marginLocked = parseFloat(usdtAsset.locked || 0)
      }
    }

    // Futures USDT balance
    const futuresTotal = futuresData && !futuresData.error ? parseFloat(futuresData.totalWalletBalance || 0) : 0
    const futuresAvailable = futuresData && !futuresData.error ? parseFloat(futuresData.availableBalance || 0) : 0
    const futuresMargin = futuresData && !futuresData.error ? parseFloat(futuresData.totalMarginBalance || 0) : 0
    const futuresUnrealizedPnl = futuresData && !futuresData.error ? parseFloat(futuresData.totalUnrealizedProfit || 0) : 0

    // Options USDT equity
    let optionsTotal = 0
    let optionsFree = 0
    if (optionsData && !optionsData.error && optionsData.asset) {
      const usdtAsset = optionsData.asset.find(a => a.asset === 'USDT')
      if (usdtAsset) {
        optionsTotal = parseFloat(usdtAsset.equity || 0)
        optionsFree = parseFloat(usdtAsset.available || 0)
      }
    }

    // Total positions from futures positionRisk
    let totalPositions = 0
    if (positionsData && !positionsData.error && Array.isArray(positionsData)) {
      positionsData.forEach(pos => {
        const amt = parseFloat(pos.positionAmt || 0)
        const price = parseFloat(pos.markPrice || 0)
        if (amt !== 0) {
          totalPositions += Math.abs(amt * price)
        }
      })
    }

    // Daily PnL = realized + unrealized
    let dailyPnl = 0
    if (dailyPnlData && !dailyPnlData.error && Array.isArray(dailyPnlData)) {
      dailyPnl = dailyPnlData.reduce((sum, item) => sum + parseFloat(item.income || 0), 0)
    }
    dailyPnl += futuresUnrealizedPnl

    // Funding fee
    let fundingFee = 0
    if (fundingFeeData && !fundingFeeData.error && Array.isArray(fundingFeeData)) {
      fundingFee = fundingFeeData.reduce((sum, item) => sum + parseFloat(item.income || 0), 0)
    }

    // Margin balance from futures USDT asset
    let marginBalance = 0
    if (futuresData && !futuresData.error && futuresData.assets) {
      const usdtAsset = futuresData.assets.find(a => a.asset === 'USDT')
      if (usdtAsset) {
        marginBalance = parseFloat(usdtAsset.marginBalance || 0)
      }
    }

    const totalMaintMargin = futuresData && !futuresData.error ? parseFloat(futuresData.totalMaintMargin || 0) : 0
    const riskRatio = futuresMargin > 0 ? (totalMaintMargin / futuresMargin * 100) : 0

    const hasError = !!(
      (spotData && spotData.error) ||
      (marginData && marginData.error) ||
      (futuresData && futuresData.error) ||
      (optionsData && optionsData.error)
    )

    results.value = {
      spot: spotData,
      margin: marginData,
      futures: futuresData,
      options: optionsData,
      // per-account totals for status display
      spotTotal,
      marginTotal,
      futuresTotal,
      optionsTotal,
      // aggregated metrics
      totalAssets: spotTotal + marginTotal + futuresTotal + optionsTotal,
      availableBalance: spotFree + marginFree + futuresAvailable + optionsFree,
      netAssets: futuresTotal,
      totalPositions,
      frozenAssets: spotLocked + marginLocked + (futuresTotal - futuresAvailable),
      dailyPnl,
      marginBalance,
      riskRatio,
      fundingFee,
      hasError,
      error: futuresData && futuresData.error ? (getBanInfo(futuresData.error) || futuresData.error.msg || '未知错误') : null
    }
  } catch (error) {
    console.error('Test failed:', error)
    results.value = {
      hasError: true,
      error: error.message
    }
  } finally {
    loading.value = false
  }
}

async function testSpotAccount() {
  try {
    const timestamp = Date.now()
    const queryString = `timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://api.binance.com/api/v3/account?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}

async function testMarginAccount() {
  try {
    const timestamp = Date.now()
    const queryString = `timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://api.binance.com/sapi/v1/margin/account?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}

async function testOptionsAccount() {
  try {
    const timestamp = Date.now()
    const queryString = `timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://eapi.binance.com/eapi/v1/account?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}

async function testFuturesAccount() {
  try {
    const timestamp = Date.now()
    const queryString = `timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://fapi.binance.com/fapi/v2/account?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}

async function testPositionRisk() {
  try {
    const timestamp = Date.now()
    const queryString = `timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://fapi.binance.com/fapi/v2/positionRisk?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}

async function testDailyPnL() {
  try {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const startTime = today.getTime()

    const timestamp = Date.now()
    const queryString = `incomeType=REALIZED_PNL&startTime=${startTime}&timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://fapi.binance.com/fapi/v1/income?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}

async function testFundingFees() {
  try {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const startTime = today.getTime()

    const timestamp = Date.now()
    const queryString = `incomeType=FUNDING_FEE&startTime=${startTime}&timestamp=${timestamp}`
    const signature = generateSignature(queryString)

    const response = await fetch(`https://fapi.binance.com/fapi/v1/income?${queryString}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': API_KEY }
    })

    if (!response.ok) {
      const error = await response.json()
      return { error: error }
    }

    return await response.json()
  } catch (error) {
    return { error: { msg: error.message } }
  }
}
</script>

<style scoped>
.binance-test-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%);
  color: #e0e0e0;
  padding: 20px;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
}

h1 {
  text-align: center;
  color: #f0b90b;
  margin-bottom: 30px;
  font-size: 2em;
}

.test-button {
  display: block;
  width: 200px;
  margin: 0 auto 30px;
  padding: 15px 30px;
  background: #f0b90b;
  color: #1e1e2e;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.3s;
}

.test-button:hover:not(:disabled) {
  background: #ffc107;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(240, 185, 11, 0.3);
}

.test-button:disabled {
  background: #666;
  cursor: not-allowed;
  transform: none;
}

.loading {
  text-align: center;
  color: #f0b90b;
  margin: 20px 0;
  font-size: 18px;
}

.account-card {
  background: #252930;
  border: 1px solid #2b3139;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
}

.account-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid #2b3139;
}

.account-name {
  font-size: 20px;
  font-weight: bold;
  color: #f0b90b;
}

.status-badge {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: bold;
}

.status-success {
  background: rgba(14, 203, 129, 0.2);
  color: #0ecb81;
}

.status-error {
  background: rgba(246, 70, 93, 0.2);
  color: #f6465d;
}

.data-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 15px;
}

.data-item {
  display: flex;
  justify-content: space-between;
  padding: 12px;
  background: #1e1e2e;
  border-radius: 8px;
}

.data-label {
  color: #888;
  font-size: 14px;
}

.data-value {
  font-family: 'Courier New', monospace;
  font-size: 14px;
  font-weight: bold;
}

.value-positive {
  color: #0ecb81;
}

.value-negative {
  color: #f6465d;
}

.value-neutral {
  color: #e0e0e0;
}

.value-unavailable {
  color: #888;
}

.value-banned {
  color: #f0b90b;
}

.api-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
  margin-bottom: 20px;
}

.api-status-item {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid;
}

.api-ok {
  background: rgba(14, 203, 129, 0.08);
  border-color: #0ecb81;
}

.api-fail {
  background: rgba(246, 70, 93, 0.08);
  border-color: #f6465d;
}

.api-name {
  display: block;
  font-size: 12px;
  color: #888;
  margin-bottom: 4px;
}

.api-value {
  display: block;
  font-family: 'Courier New', monospace;
  font-size: 14px;
  font-weight: bold;
  color: #e0e0e0;
}

.api-error {
  display: block;
  font-size: 11px;
  color: #f6465d;
  margin-top: 4px;
  word-break: break-all;
}

.error-message {
  background: rgba(246, 70, 93, 0.1);
  border: 1px solid #f6465d;
  border-radius: 8px;
  padding: 15px;
  margin-top: 15px;
  color: #f6465d;
  font-size: 14px;
}
</style>
