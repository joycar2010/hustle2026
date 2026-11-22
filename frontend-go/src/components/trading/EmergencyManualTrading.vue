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
          :disabled="inflight || loading"
          class="btn btn-buy"
        >
          买入开多
        </button>
        <button
          @click="executeTrade('sell')"
          :disabled="inflight || loading"
          class="btn btn-sell"
        >
          卖出开空
        </button>
      </div>

      <!-- Close Position Buttons -->
      <div class="close-buttons">
        <button
          @click="closePosition('long')"
          :disabled="inflight || loading"
          class="btn btn-close-long"
        >
          多仓平空
        </button>
        <button
          @click="closePosition('short')"
          :disabled="inflight || loading"
          class="btn btn-close-short"
        >
          空仓平多
        </button>
      </div>

      <!-- Status message -->
      <div v-if="statusMsg" :class="['status-msg', statusClass]">
        {{ statusMsg }}
      </div>

      <!-- Quick Actions -->
      <div class="quick-actions">
        <button
          @click="closeAllPositions"
          :disabled="inflight || loading"
          class="btn btn-danger"
        >
          平仓所有持仓
        </button>
        <button
          @click="cancelAllOrders"
          :disabled="inflight || loading"
          class="btn btn-secondary"
        >
          取消所有挂单
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import api from '@/services/api'
import { useTradingPair } from '@/composables/useTradingPair'
import { useMarketStore } from '@/stores/market'
import { PlatformId, platformKey } from '@/constants/platform'

const emit = defineEmits(['orderExecuted'])

const { currentPair, pairConfig } = useTradingPair()

// Per-user WS results arrive via the SAME mechanism StrategyPanel.vue uses:
// the market store's `lastMessage` ref (manual_trade_result is NOT a strategy_*
// type, so it lands in lastMessage, not strategyMessage). We do NOT open a raw WS.
const marketStore = useMarketStore()

// Component-level single-flight lock: ALL six buttons stay disabled from the
// moment any action is fired until its manual_trade_result arrives (or the
// 8s watchdog fires). pendingReqs maps request_id -> { timer, action }.
const inflight = ref(false)
const pendingReqs = ref(new Map())

// Human labels for the per-action messages.
const ACTION_LABELS = {
  'order': '下单',
  'close-long': '多仓平空',
  'close-short': '空仓平多',
  'close-all': '平仓所有持仓',
  'cancel-all': '取消所有挂单',
}

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
// Three-state status: 'success' (green) | 'error' (red) | 'warn' (amber).
// 'warn' is used for the watchdog's unconfirmed-result case — amber, NOT success.
const statusKind = ref('success')
const statusClass = computed(() => `status-${statusKind.value}`)

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

// kind: true|'success' (green), false|'error' (red), 'warn' (amber).
function showStatus(msg, kind = 'success') {
  const k = kind === true ? 'success' : kind === false ? 'error' : kind
  statusKind.value = k
  statusOk.value = k === 'success'
  statusMsg.value = msg
  setTimeout(() => { statusMsg.value = '' }, 4000)
}

// Generate a fresh correlation id for one click.
function newRequestId() {
  return (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : String(Date.now()) + Math.random()
}

// Track an async (202) action's result AND lock the buttons until the result
// (manual_trade_result WS) arrives or the watchdog fires. 防重入根因修复
// (2026-06-26): 此前 inflight 从未被置 true, 按钮仅在 ~300ms HTTP 往返期(loading)
// 被禁用, 202 ACK 一回来 finally 即点亮按钮 —— 而真正下单还在后台跑。用户第二次触碰
// (手抖/触摸重复派发/回车)就发出另一笔【独立 request_id】的相同单, 后端单飞窗口仅 6s
// 拦不住相隔较久的二次提交 → 出现"感觉没操作却又开一单"。修复: 调用方在 202 分支置
// inflight=true, 此处 watchdog 超时复位; WS 回执处(manual_trade_result watcher)也复位。
function armWatchdog(request_id, action) {
  const timer = setTimeout(() => {
    pendingReqs.value.delete(request_id)
    inflight.value = false  // 结果迟迟未到, 解锁按钮(避免永久卡死), 并提示用户自查
    showStatus('结果未确认，请核对持仓/挂单', 'warn')
  }, 8000)
  pendingReqs.value.set(request_id, { timer, action })
}

async function executeTrade(side, confirmDuplicate = false) {
  if (loading.value) return
  loading.value = true
  try {
    const actualQuantity = convertForPlatform(quantity.value, exchange.value)
    const price = customParam.value ? parseFloat(customParam.value) : null
    // No client-side fetchMarketPrice()/validateCustomPrice pre-call: the
    // backend re-fetches the live quote and applies the authoritative
    // price-deviation guard synchronously (returns 4xx) before the ACK.

    const request_id = newRequestId()
    const payload = {
      exchange: exchange.value,
      side,
      quantity: actualQuantity,
      pair_code: currentPair.value,
      request_id,
    }
    if (price) payload.price = price
    payload.order_type = exchange.value === EXCHANGE_BINANCE ? 'maker' : 'taker'
    if (confirmDuplicate) payload.confirm_duplicate = true

    const res = await api.post('/api/v1/trading/manual/order', payload)
    const rid = res.data?.request_id
    if (rid) {
      // Async (202): stay disabled until manual_trade_result or watchdog.
      inflight.value = true  // 防重入: 保持按钮禁用直到 WS 回执/watchdog 超时
      armWatchdog(rid, 'order')
      showStatus('指令已发送，执行中…', true)
    } else {
      // Synchronous success (no request_id echoed): already executed.
      showStatus(`${side === 'buy' ? '买入' : '卖出'}指令已发送 (${exchange.value === EXCHANGE_BINANCE ? 'Maker' : price ? 'Limit' : 'Market'})`, true)
      emit('orderExecuted')
    }
  } catch (e) {
    inflight.value = false
    const status = e.response?.status
    const detail = e.response?.data?.detail
    // 后端重复开仓兜底: 409 + DUPLICATE_CONFIRM → 二次确认后带 confirm_duplicate 重发
    if (status === 409 && detail && typeof detail === 'object' && detail.code === 'DUPLICATE_CONFIRM') {
      loading.value = false
      if (confirm(detail.message || '检测到短时间内的重复开仓，确认要再下一笔吗？')) {
        return executeTrade(side, true)
      }
      showStatus('已取消重复下单', 'warn')
      return
    }
    const detailMsg = (typeof detail === 'string') ? detail : (detail?.message)
    showStatus(status === 409 ? '重复指令执行中' : (detailMsg || '下单失败'), false)
  } finally {
    loading.value = false
  }
}

async function closePosition(positionType) {
  if (loading.value) return
  loading.value = true
  try {
    const actualQuantity = convertForPlatform(quantity.value, exchange.value)
    const action = positionType === 'short' ? 'close-short' : 'close-long'
    const endpoint = `/api/v1/trading/manual/${action}`
    const price = customParam.value ? parseFloat(customParam.value) : null
    // Backend re-fetches the live quote and applies the authoritative
    // price-deviation guard synchronously before the ACK.

    const request_id = newRequestId()
    const payload = {
      exchange: exchange.value,
      quantity: actualQuantity,
      pair_code: currentPair.value,
      request_id,
    }
    if (price) payload.price = price
    payload.order_type = exchange.value === EXCHANGE_BINANCE ? 'maker' : 'taker'

    const res = await api.post(endpoint, payload)
    const rid = res.data?.request_id
    if (rid) {
      inflight.value = true  // 防重入: 保持按钮禁用直到 WS 回执/watchdog 超时
      armWatchdog(rid, action)
      showStatus('指令已发送，执行中…', true)
    } else {
      showStatus(`${positionType === 'short' ? '空仓平多' : '多仓平空'}指令已发送`, true)
      emit('orderExecuted')
    }
  } catch (e) {
    inflight.value = false
    const status = e.response?.status
    showStatus(status === 409 ? '重复指令执行中' : (e.response?.data?.detail || '平仓失败'), false)
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
    const request_id = newRequestId()
    const res = await api.post('/api/v1/trading/manual/close-all', {
      pair_code: currentPair.value,
      request_id,
    })
    const rid = res.data?.request_id
    if (rid) {
      inflight.value = true  // 防重入: 保持按钮禁用直到 WS 回执/watchdog 超时
      armWatchdog(rid, 'close-all')
      showStatus('指令已发送，执行中…', true)
    } else {
      showStatus(`平仓指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
      emit('orderExecuted')
    }
  } catch (e) {
    inflight.value = false
    const status = e.response?.status
    showStatus(status === 409 ? '重复指令执行中' : (e.response?.data?.detail || '平仓失败'), false)
  } finally {
    loading.value = false
  }
}

async function cancelAllOrders() {
  if (!confirm('确定要取消所有挂单吗？')) return
  if (loading.value) return
  loading.value = true
  try {
    const request_id = newRequestId()
    const res = await api.post('/api/v1/trading/manual/cancel-all', {
      pair_code: currentPair.value,
      request_id,
    })
    const rid = res.data?.request_id
    if (rid) {
      inflight.value = true  // 防重入: 保持按钮禁用直到 WS 回执/watchdog 超时
      armWatchdog(rid, 'cancel-all')
      showStatus('指令已发送，执行中…', true)
    } else {
      showStatus(`撤单指令已发送，共 ${res.data.results?.length || 0} 笔`, true)
      emit('orderExecuted')
    }
  } catch (e) {
    inflight.value = false
    const status = e.response?.status
    showStatus(status === 409 ? '重复指令执行中' : (e.response?.data?.detail || '撤单失败'), false)
  } finally {
    loading.value = false
  }
}

// ── Per-user WS result watcher ─────────────────────────────────────────────
// Reuses the SAME mechanism StrategyPanel.vue uses: the market store's
// `lastMessage` ref. `manual_trade_result` is delivered over the production
// per-user path (Redis ws:user_event -> hub) and is NOT a strategy_* type, so
// it lands in lastMessage. We resolve only request_ids we ourselves armed.
watch(() => marketStore.lastMessage, (message) => {
  if (!message || message.type !== 'manual_trade_result') return
  const data = message.data || {}
  const rid = data.request_id
  if (!rid || !pendingReqs.value.has(rid)) return

  const entry = pendingReqs.value.get(rid)
  clearTimeout(entry.timer)
  pendingReqs.value.delete(rid)
  inflight.value = false

  if (data.success) {
    if (entry.action === 'cancel-all') {
      const rs = Array.isArray(data.results) ? data.results : []
      const summ = rs.find(r => r && r.kind === 'cancel_summary')
      const mc = summ ? (summ.manual_cancelled || 0) : rs.filter(r => r && r.success && r.client_order_id).length
      const sk = summ ? (summ.strategy_kept || 0) : 0
      let msg = mc > 0 ? `已撤手动挂单 ${mc} 笔` : '未发现手动挂单'
      if (sk > 0) msg += `，保留自动策略挂单 ${sk} 笔（如需撤销请到策略面板停止策略）`
      showStatus(msg, true)
    } else {
      showStatus('执行成功', true)
    }
  } else {
    // Prefer an explicit top-level error; otherwise summarize failing legs
    // (close-all/cancel-all may attempt several legs).
    let msg = data.error
    if (!msg && Array.isArray(data.results)) {
      const failed = data.results.filter(r => r && r.success === false)
      if (failed.length) {
        msg = failed
          .map(r => `${r.leg || r.exchange || '腿'}: ${r.error || '失败'}`)
          .join('；')
      }
    }
    const label = ACTION_LABELS[entry.action] || entry.action || '指令'
    showStatus(msg ? `${label}失败 — ${msg}` : `${label}失败`, false)
  }
  // Refresh positions/orders regardless of success.
  emit('orderExecuted')
})

onUnmounted(() => {
  for (const { timer } of pendingReqs.value.values()) clearTimeout(timer)
  pendingReqs.value.clear()
})
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

.status-warn {
  color: #f0b90b;
  background-color: rgba(240, 185, 11, 0.1);
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
