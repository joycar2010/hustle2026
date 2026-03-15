<template>
  <div class="emergency-trading-container">
    <div class="header">
      <h3 class="title">紧急手动交易</h3>
      <div class="emergency-badge">
        <div class="pulse-dot"></div>
        <span class="badge-text">紧急模式</span>
      </div>
    </div>

    <div class="content">
      <!-- Exchange Selection -->
      <div class="form-group">
        <label class="label">交易平台</label>
        <select v-model="exchange" class="select-input">
          <option value="binance">Binance (XAUUSDT)</option>
          <option value="bybit">Bybit MT5 (XAUUSD.s)</option>
        </select>
      </div>

      <!-- Quantity -->
      <div class="form-group">
        <label class="label">下单总手数 (XAU)</label>
        <input
          v-model.number="quantity"
          type="number"
          step="1"
          min="1"
          class="text-input"
          placeholder="1"
        />
        <div class="hint-text">
          Bybit 实际下单量: {{ xauToLot(quantity).toFixed(2) }} Lot
        </div>
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
          @click="closePosition('short')"
          :disabled="loading"
          class="btn btn-close-short"
        >
          空仓平多
        </button>
        <button
          @click="closePosition('long')"
          :disabled="loading"
          class="btn btn-close-long"
        >
          多仓平空
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
          ⚠️ 平仓所有持仓
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
import { ref } from 'vue'
import api from '@/services/api'
import { xauToLot, convertForPlatform } from '@/composables/useQuantityConverter'

const emit = defineEmits(['orderExecuted'])

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

    await api.post(endpoint, {
      exchange: exchange.value,
      quantity: actualQuantity,
    })
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
    const res = await api.post('/api/v1/trading/manual/close-all')
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
    const res = await api.post('/api/v1/trading/manual/cancel-all')
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

.btn-buy {
  background-color: #0ecb81;
}

.btn-buy:hover:not(:disabled) {
  background-color: #0db774;
}

.btn-sell {
  background-color: #f6465d;
}

.btn-sell:hover:not(:disabled) {
  background-color: #e03d52;
}

.btn-close-short {
  background-color: #f0b90b;
}

.btn-close-short:hover:not(:disabled) {
  background-color: #d9a509;
}

.btn-close-long {
  background-color: #f0b90b;
}

.btn-close-long:hover:not(:disabled) {
  background-color: #d9a509;
}

.btn-danger {
  background-color: #f6465d;
}

.btn-danger:hover:not(:disabled) {
  background-color: #e03d52;
}

.btn-secondary {
  background-color: #252930;
}

.btn-secondary:hover:not(:disabled) {
  background-color: #2b3139;
}

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

/* 移动端H5竖屏适配 */
@media (orientation: portrait), (max-width: 750px) {
  .emergency-trading-container {
    width: 100%;
    max-height: 400px;
    box-sizing: border-box;
  }

  .content {
    padding: 12px;
  }

  .btn {
    min-height: 44px; /* 移动端最小点击区域 */
  }
}

/* PC端保持原有布局 */
@media (min-width: 751px) and (orientation: landscape) {
  .emergency-trading-container {
    /* PC端样式保持不变 */
  }
}
</style>
