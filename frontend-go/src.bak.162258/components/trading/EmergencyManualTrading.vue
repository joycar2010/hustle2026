<template>
  <div class="emergency-trading-container">
    <div class="header">
      <h3 class="title">紧急手动交易</h3>
      <div class="emergency-badge">
        <div class="pulse-dot"></div>
        <span class="badge-text">{{ currentPair }}</span>
      </div>
    </div>

    <div class="content">
      <!-- Exchange Selection -->
      <div class="form-group">
        <label class="label">交易平台</label>
        <select v-model="exchange" class="select-input">
          <option :value="EXCHANGE_BINANCE">主账号 ({{ pairConfig.binance }})</option>
          <option :value="EXCHANGE_BYBIT">对冲账户 ({{ pairConfig.mt5 }})</option>
        </select>
      </div>

      <!-- Quantity + Custom Input (two-column, aligned with Buy/Sell buttons) -->
      <div class="qty-row">
        <div class="form-group qty-col">
          <label class="label">下单数量 ({{ aUnitLabel }})</label>
          <input
            v-model.number="quantity"
            type="number"
            step="1"
            min="1"
            class="text-input"
            placeholder="1"
          />
          <div class="hint-text">
            对冲: {{ convertedQty }} {{ bUnitLabel }}
          </div>
        </div>
        <div class="form-group qty-col">
          <label class="label">自定义价格</label>
          <input
            v-model="customParam"
            type="text"
            inputmode="decimal"
            class="text-input"
            :placeholder="'0.' + '0'.repeat(priceDecimals)"
            @input="onCustomParamInput"
          />
          <div class="hint-text">&nbsp;</div>
        </div>
      </div>

      <!-- Mode Hint -->
      <div class="mode-hint">
        <span class="mode-dot" :class="exchange === EXCHANGE_BINANCE ? 'dot-maker' : 'dot-taker'"></span>
        <span class="mode-text">{{ modeHint }}</span>
      </div>

      <!-- Action Buttons -->
      <div class="action-buttons">
        <button
          @click="executeTrade('buy')"
          :disabled="loading"
          class="btn btn-buy"
        >
          买入开多
        </button>
        <button
          @click="executeTrade('sell')"
          :disabled="loading"
          class="btn btn-sell"
        >
          卖出开空
        </button>
      </div>

      <!-- Close Position Buttons -->
      <div class="close-buttons">
        <button
          @click="closePosition('long')"
          :disabled="loading"
          class="btn btn-close-long"
        >
          多仓平空
        </button>
        <button
          @click="closePosition('short')"
          :disabled="loading"
          class="btn btn-close-short"
        >
          空仓平多
        </button>
      </div>

      <!-- Status message -->
      <div v-if="statusMsg" :class="['status-msg', statusOk ? 'status-success' : 'status-error']">
        {{ statusMsg }}
      </div>

      <!-- Quick Actions -->
      <div class="quick-actions">
        <button
          @click="closeAllPositions"
          :disabled="loading"
          class="btn btn-danger"
        >
          平仓所有持仓
        </button>
        <button
          @click="cancelAllOrders"
          :disabled="loading"
          class="btn btn-secondary"
        >
          取消所有挂单
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '@/services/api'
import { useTradingPair } from '@/composables/useTradingPair'
import { PlatformId, platformKey } from '@/constants/platform'

const emit = defineEmits(['orderExecuted'])

const { currentPair, pairConfig } = useTradingPair()

const EXCHANGE_BINANCE = platformKey(PlatformId.BINANCE)  // 'binance'
const EXCHANGE_BYBIT = platformKey(PlatformId.BYBIT)      // 'bybit'
const exchange = ref(EXCHANGE_BINANCE)
const quantity = ref(1)
const customParam = ref('')

const priceDecimals = computed(() => {
  const code = currentPair.value
  if (['NG'].includes(code)) return 4
  if (['BZ', 'CL'].includes(code)) return 3
  return 2
})

function onCustomParamInput(e) {
  let v = e.target.value
  v = v.replace(/[^0-9.]/g, '')
  const parts = v.split('.')
  if (parts.length > 2) v = parts[0] + '.' + parts.slice(1).join('')
  const maxDec = priceDecimals.value
  if (parts.length === 2 && parts[1].length > maxDec) v = parts[0] + '.' + parts[1].slice(0, maxDec)
  customParam.value = v
  e.target.value = v
}
const modeHint = computed(() => {
  const isBinance = exchange.value === EXCHANGE_BINANCE
  const hasPrice = !!customParam.value
  if (isBinance) return hasPrice ? 'Maker · 固定价' : 'Maker · 自动挂单价'
  return hasPrice ? 'Limit · 固定价' : 'Market · 即时成交'
})

const loading = ref(false)
const statusMsg = ref('')
const statusOk = ref(true)

// Dynamic unit labels based on pair config
const aUnitLabel = computed(() => pairConfig.value.unitA || 'XAU')
const bUnitLabel = computed(() => pairConfig.value.unitB || 'Lot')

// Convert A-side quantity to B-side display
const convertedQty = computed(() => {
  const conv = pairConfig.value.conversionFactor || 100
  const val = (quantity.value || 0) / conv
  return val.toFixed(2)
})

// Convert quantity for the selected platform
function convertForPlatform(qty, exch) {
  if (exch === 'bybit') {
    const conv = pairConfig.value.conversionFactor || 100
    return Number((qty / conv).toFixed(2))
  }
  return qty
}

function showStatus(msg, ok = true) {
  statusMsg.value = msg
  statusOk.value = ok
  setTimeout(() => { statusMsg.value = '' }, 4000)
}

async function fetchMarketPrice() {
  const cfg = pairConfig.value
  const r = await api.get('/api/v1/market/spread', { params: { binance_symbol: cfg.binance, bybit_symbol: cfg.mt5 } })
  return r.data
}

function validateCustomPrice(price, side, spreadData) {
  const isBinance = exchange.value === EXCHANGE_BINANCE
  const quote = isBinance ? spreadData?.binance_quote : spreadData?.bybit_quote
  const bid = quote?.bid_price || 0
  const ask = quote?.ask_price || 0
  const mid = (bid + ask) / 2
  if (!mid) return null

  const deviation = Math.abs(price - mid) / mid
  if (deviation > 0.02) {
    const platform = isBinance ? '主账号' : '对冲账号'
    return `挂单价 ${price} 偏离${platform}市场价 ${mid.toFixed(2)} 超过2% (${(deviation * 100).toFixed(1)}%)，请确认价格是否正确`
  }

  if (isBinance) {
    if (side === 'buy' && price >= ask) {
      return `买入价 ${price} >= 卖一价 ${ask.toFixed(2)}，Maker单会被拒绝(会吃单)。请降低价格或改用对冲账号。`
    }
    if (side === 'sell' && price <= bid) {
      return `卖出价 ${price} <= 买一价 ${bid.toFixed(2)}，Maker单会被拒绝(会吃单)。请提高价格或改用对冲账号。`
    }
  }
  return null
}

async function executeTrade(side) {
  if (loading.value) return
  loading.value = true
  try {
    const actualQuantity = convertForPlatform(quantity.value, exchange.value)
    const price = customParam.value ? parseFloat(customParam.value) : null

    if (price) {
      const spread = await fetchMarketPrice()
      const err = validateCustomPrice(price, side, spread)
      if (err) {
        if (!confirm(err + '\n\n确定继续下单吗？')) {
          loading.value = false
          return
        }
      }
    }

    const payload = {
      exchange: exchange.value,
      side,
      quantity: actualQuantity,
      pair_code: currentPair.value,
    }
    if (price) payload.price = price
    payload.order_type = exchange.value === EXCHANGE_BINANCE ? 'maker' : 'taker'

    await api.post('/api/v1/trading/manual/order', payload)
    showStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送 (${exchange.value === EXCHANGE_BINANCE ? 'Maker' : price ? 'Limit' : 'Market'})`, true)
    emit('orderExecuted')
  } catch (e) {
    showStatus(e.response?.data?.detail || '下单失败', false)
  } finally {
    loading.value = false
  }
}

async function closePosition(positionType) {
  if (loading.value) return
  loading.value = true
  try {
    const actualQuantity = convertForPlatform(quantity.value, exchange.value)
    const endpoint = positionType === 'short' ? '/api/v1/trading/manual/close-short' : '/api/v1/trading/manual/close-long'
    const price = customParam.value ? parseFloat(customParam.value) : null

    if (price) {
      const closeSide = positionType === 'short' ? 'buy' : 'sell'
      const spread = await fetchMarketPrice()
      const err = validateCustomPrice(price, closeSide, spread)
      if (err) {
        if (!confirm(err + '\n\n确定继续下单吗？')) {
          loading.value = false
          return
        }
      }
    }

    const payload = {
      exchange: exchange.value,
      quantity: actualQuantity,
      pair_code: currentPair.value,
    }
    if (price) payload.price = price
    payload.order_type = exchange.value === EXCHANGE_BINANCE ? 'maker' : 'taker'

    await api.post(endpoint, payload)
    showStatus(`${positionType === 'short' ? '空仓平多' : '多仓平空'}指令已发送`, true)
    emit('orderExecuted')
  } catch (e) {
    showStatus(e.response?.data?.detail || '平仓失败', false)
  } finally {
    loading.value = false
  }
}

async function closeAllPositions() {
  if (!confirm('确定要平仓所有持仓吗？此操作不可撤销！')) return
  if (!confirm('再次确认：真的要平仓所有持仓吗？')) return
  if (loading.value) return
  loading.value = true
  try {
    const res = await api.post('/api/v1/trading/manual/close-all', {
      pair_code: currentPair.value,
    })
    showStatus(`平仓指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    emit('orderExecuted')
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
    const res = await api.post('/api/v1/trading/manual/cancel-all', {
      pair_code: currentPair.value,
    })
    showStatus(`撤单指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
    emit('orderExecuted')
  } catch (e) {
    showStatus(e.response?.data?.detail || '撤单失败', false)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.emergency-trading-container {
  display: flex;
  flex-direction: column;
  background-color: #1e2329;
  border-radius: 8px;
  overflow: hidden;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid #2b3139;
  flex-shrink: 0;
}

.title {
  font-size: 11px;
  font-weight: bold;
  color: #ffffff;
  margin: 0;
}

.emergency-badge {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #f6465d;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.badge-text {
  font-size: 10px;
  font-weight: bold;
  color: #f6465d;
}

.content {
  overflow-y: auto;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.label {
  font-size: 10px;
  color: #848e9c;
}

.select-input,
.text-input {
  width: 100%;
  background-color: #252930;
  border: 1px solid #2b3139;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 12px;
  color: #ffffff;
  box-sizing: border-box;
}

.select-input:focus,
.text-input:focus {
  outline: none;
  border-color: #f0b90b;
}

.hint-text {
  font-size: 10px;
  color: #848e9c;
}

.action-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.close-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.btn {
  padding: 6px 10px;
  border: none;
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
  color: #ffffff;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-buy { background-color: #0ecb81; }
.btn-buy:hover:not(:disabled) { background-color: #0db774; }
.btn-sell { background-color: #f6465d; }
.btn-sell:hover:not(:disabled) { background-color: #e03d52; }
.btn-close-short { background-color: #f0b90b; }
.btn-close-short:hover:not(:disabled) { background-color: #d9a509; }
.btn-close-long { background-color: #f0b90b; }
.btn-close-long:hover:not(:disabled) { background-color: #d9a509; }
.btn-danger { background-color: #f6465d; }
.btn-danger:hover:not(:disabled) { background-color: #e03d52; }
.btn-secondary { background-color: #252930; }
.btn-secondary:hover:not(:disabled) { background-color: #2b3139; }

.status-msg {
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 10px;
}

.status-success {
  color: #0ecb81;
  background-color: rgba(14, 203, 129, 0.1);
}

.status-error {
  color: #f6465d;
  background-color: rgba(246, 70, 93, 0.1);
}

.quick-actions {
  padding-top: 8px;
  border-top: 1px solid #2b3139;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.qty-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.qty-col {
  min-width: 0;
}

.mode-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background-color: #252930;
  border-radius: 4px;
  margin-top: -4px;
}

.mode-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.dot-maker {
  background-color: #0ecb81;
}

.dot-taker {
  background-color: #f0b90b;
}

.mode-text {
  font-size: 10px;
  color: #848e9c;
  font-weight: 500;
}

@media (orientation: portrait), (max-width: 750px) {
  .emergency-trading-container {
    width: 100%;
    max-height: 400px;
    box-sizing: border-box;
  }
  .content { padding: 12px; }
  .btn { min-height: 44px; }
}
</style>
