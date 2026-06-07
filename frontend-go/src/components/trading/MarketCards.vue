<template>
  <div class="h-full flex flex-col max-lg:h-auto overflow-hidden w-full">
    <!-- System Status Marquee (all notifications unified) -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <button
        @click="showSystemStatusModal = true"
        :class="['w-full flex items-center px-3 py-2 rounded-lg transition-colors cursor-pointer', marqueeButtonBg]"
        :title="'点击查看详细系统状态'"
      >
        <div class="marquee-container w-full overflow-hidden">
          <div :class="['marquee-content text-xs whitespace-nowrap', marqueeColorClass]">
            {{ marqueeText }}
          </div>
        </div>
      </button>
    </div>

    <!-- Total Profit Header -->
    <div class="p-1.5 lg:p-1.5 md:p-2 bg-[#252930] border-b border-[#2b3139] flex-shrink-0 w-full">
      <div class="bg-[#1e2329] rounded p-1.5 lg:p-1 flex items-center justify-center gap-2 w-full">
        <span class="text-xs lg:text-[10px] text-gray-400">实时持仓盈利</span>
        <span class="text-base lg:text-sm md:text-lg font-bold font-mono" :class="totalProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
          {{ totalProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(totalProfit)) }}
        </span>
        <span class="text-xs lg:text-[10px] text-gray-400">USDT</span>
      </div>
      <!-- 主账户 / 对冲账户盈亏明细 -->
      <div class="bg-[#1e2329] rounded p-1 flex items-center justify-between gap-1 w-full mt-1">
        <div class="flex items-center gap-1.5 flex-1 min-w-0">
          <span class="text-[10px] text-gray-500 whitespace-nowrap">主账户</span>
          <span class="text-xs font-mono font-bold" :class="binanceFloatingProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ binanceFloatingProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(binanceFloatingProfit)) }}
          </span>
          <span class="text-[10px] text-gray-600">|</span>
          <span class="text-[10px] text-gray-500">资金费</span>
          <span class="text-[10px] font-mono" :class="mainFundingFee >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ mainFundingFee >= 0 ? '+' : '' }}{{ mainFundingFee.toFixed(2) }}
          </span>
        </div>
        <div class="w-px h-3 bg-[#2b3139]"></div>
        <div class="flex items-center gap-1.5 flex-1 min-w-0 justify-end">
          <span class="text-[10px] text-gray-500 whitespace-nowrap">对冲账户</span>
          <span class="text-xs font-mono font-bold" :class="bybitFloatingProfit >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ bybitFloatingProfit >= 0 ? '+' : '' }}{{ formatNumber(Math.abs(bybitFloatingProfit)) }}
          </span>
          <span class="text-[10px] text-gray-600">|</span>
          <span class="text-[10px] text-gray-500">过夜费</span>
          <span class="text-[10px] font-mono" :class="hedgeOvernightFee >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
            {{ hedgeOvernightFee >= 0 ? '+' : '' }}{{ hedgeOvernightFee.toFixed(2) }}
          </span>
        </div>
      </div>
    </div>

    <!-- Content Area -->
    <div class="flex-1 overflow-y-auto overflow-x-hidden p-1.5 lg:p-1 md:p-2 scrollbar-hide">
      <div class="grid grid-cols-1 gap-1.5 lg:gap-1 md:gap-2">
      <!-- 对冲账户 Card -->
      <div class="bg-[#252930] rounded p-1.5 lg:p-1.5 md:p-2 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="font-medium text-sm lg:text-xs md:text-base"><span :class="['inline-block w-1.5 h-1.5 rounded-full mr-1 transition-opacity duration-200', dataAlive ? 'bg-[#0ecb81] opacity-100' : 'bg-gray-600 opacity-40']"></span>对冲账户 <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">{{ pairConfig.mt5 }}</span></div>
        </div>

        <!-- Real-time Price with liquidation prices on left (long) and right (short) -->
        <div class="mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400 text-center">实时价格</div>
            <div class="flex items-center justify-between gap-1">
              <!-- 多头强平价（左侧）-->
              <div class="flex flex-col items-start min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">多强平</span>
                <span :class="['text-[20px] lg:text-[18px] font-mono font-bold leading-tight', liqDanger.mt5Long ? 'liq-flash text-[#ff0000]' : 'text-[#0ecb81]']">
                  {{ currentLiq.mt5.long != null ? formatPrice(currentLiq.mt5.long) : '暂无' }}
                  <span v-if="liqDanger.mt5Long" class="text-[10px]">{{ liqDistPct(currentLiq.mt5.long, bybit.mid) }}%</span>
                </span>
              </div>
              <!-- 实时价格（中间）-->
              <div class="text-xl lg:text-lg md:text-2xl font-mono font-bold text-[#0ecb81] text-center flex-1">
                {{ formatPrice(bybit.mid) }}
              </div>
              <!-- 空头强平价（右侧）-->
              <div class="flex flex-col items-end min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">空强平</span>
                <span :class="['text-[20px] lg:text-[18px] font-mono font-bold leading-tight', liqDanger.mt5Short ? 'liq-flash text-[#ff0000]' : 'text-[#f6465d]']">
                  {{ currentLiq.mt5.short != null ? formatPrice(currentLiq.mt5.short) : '暂无' }}
                  <span v-if="liqDanger.mt5Short" class="text-[10px]">{{ liqDistPct(currentLiq.mt5.short, bybit.mid) }}%</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-1 lg:gap-0.5 md:gap-1.5 mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">ASK</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(bybit.ask, bybit.prevAsk)]">
              {{ formatPrice(bybit.ask) }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">BID</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(bybit.bid, bybit.prevBid)]">
              {{ formatPrice(bybit.bid) }}
            </div>
          </div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-0.5 lg:pt-0.5 md:pt-1 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1 lg:space-x-0.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-0.5 lg:w-0.5 h-2 lg:h-1.5 md:h-2.5 rounded-sm', i <= bybitLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span
              @dblclick="resetBybitLag"
              class="text-[10px] lg:text-[9px] md:text-xs font-mono cursor-pointer hover:text-[#f0b90b] transition-colors"
              title="双击清零"
            >{{ bybitLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- 主账号 Card -->
      <div class="bg-[#252930] rounded p-1.5 lg:p-1.5 md:p-2 flex flex-col border border-[#2b3139]">
        <div class="flex items-center justify-center mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="font-medium text-sm lg:text-xs md:text-base"><span :class="['inline-block w-1.5 h-1.5 rounded-full mr-1 transition-opacity duration-200', dataAlive ? 'bg-[#0ecb81] opacity-100' : 'bg-gray-600 opacity-40']"></span>主账号 <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">{{ pairConfig.binance }}</span></div>
        </div>

        <!-- Real-time Price with liquidation prices on left (long) and right (short) -->
        <div class="mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139]">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400 text-center">实时价格</div>
            <div class="flex items-center justify-between gap-1">
              <!-- 多头强平价（左侧）-->
              <div class="flex flex-col items-start min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">多强平</span>
                <span :class="['text-[20px] lg:text-[18px] font-mono font-bold leading-tight', liqDanger.binanceLong ? 'liq-flash text-[#ff0000]' : 'text-[#0ecb81]']">
                  {{ currentLiq.binance.long != null ? formatPrice(currentLiq.binance.long) : '暂无' }}
                  <span v-if="liqDanger.binanceLong" class="text-[10px]">{{ liqDistPct(currentLiq.binance.long, binance.mid) }}%</span>
                </span>
              </div>
              <!-- 实时价格（中间）-->
              <div class="text-xl lg:text-lg md:text-2xl font-mono font-bold text-[#f6465d] text-center flex-1">
                {{ formatPrice(binance.mid) }}
              </div>
              <!-- 空头强平价（右侧）-->
              <div class="flex flex-col items-end min-w-0 shrink-0">
                <span class="text-[18px] lg:text-[16px] text-gray-500 leading-none">空强平</span>
                <span :class="['text-[20px] lg:text-[18px] font-mono font-bold leading-tight', liqDanger.binanceShort ? 'liq-flash text-[#ff0000]' : 'text-[#f6465d]']">
                  {{ currentLiq.binance.short != null ? formatPrice(currentLiq.binance.short) : '暂无' }}
                  <span v-if="liqDanger.binanceShort" class="text-[10px]">{{ liqDistPct(currentLiq.binance.short, binance.mid) }}%</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- ASK and BID in one row -->
        <div class="grid grid-cols-2 gap-1 lg:gap-0.5 md:gap-1.5 mb-1 lg:mb-0.5 md:mb-1.5">
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139] relative cursor-pointer hover:border-[#3b4149] transition-colors" @click="showPendingOrdersModal('ASK')">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">ASK</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(binance.ask, binance.prevAsk)]">
              {{ formatPrice(binance.ask) }}
            </div>
            <!-- 行情卖一: 量 + 价 (左→右) -->
            <div class="flex justify-between mt-0.5 text-[11px] lg:text-[10px] md:text-sm font-mono">
              <span class="text-[#3b82f6]">{{ formatVolume(binanceOrderBook.ask_volume) }}</span>
              <span class="text-[#0ecb81]">{{ formatPrice(binanceOrderBook.ask_price) }}</span>
            </div>
            <div v-if="askOrderCount > 0" class="absolute top-0.5 right-0.5 bg-yellow-600 text-white text-[9px] px-1 py-0.5 rounded font-bold">
              挂{{ askOrderCount }}
            </div>
          </div>
          <div class="bg-[#1e2329] rounded px-1.5 lg:px-1 py-0.5 lg:py-0.5 md:py-1 border border-[#2b3139] relative cursor-pointer hover:border-[#3b4149] transition-colors" @click="showPendingOrdersModal('BID')">
            <div class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">BID</div>
            <div :class="['text-xl lg:text-lg md:text-2xl font-mono font-bold', getPriceClass(binance.bid, binance.prevBid)]">
              {{ formatPrice(binance.bid) }}
            </div>
            <!-- 行情买一: 价 + 量 (左→右) -->
            <div class="flex justify-between mt-0.5 text-[11px] lg:text-[10px] md:text-sm font-mono">
              <span class="text-[#f6465d]">{{ formatPrice(binanceOrderBook.bid_price) }}</span>
              <span class="text-[#3b82f6]">{{ formatVolume(binanceOrderBook.bid_volume) }}</span>
            </div>
            <div v-if="bidOrderCount > 0" class="absolute top-0.5 right-0.5 bg-yellow-600 text-white text-[9px] px-1 py-0.5 rounded font-bold">
              挂{{ bidOrderCount }}
            </div>
          </div>
        </div>

        <!-- User Pending Orders Row (当前用户 Binance 实时挂单: ASK 价格/数量 + BID 价格/数量) -->
        <div class="grid grid-cols-4 gap-0.5 mb-1 lg:mb-0.5 md:mb-1.5 text-base lg:text-sm md:text-xl">
          <div class="text-center text-[#3b82f6] font-mono">{{ formatVolume(userAskOrder.quantity) }}</div>
          <div class="text-center text-[#0ecb81] font-mono">{{ formatPrice(userAskOrder.price) }}</div>
          <div class="text-center text-[#f6465d] font-mono">{{ formatPrice(userBidOrder.price) }}</div>
          <div class="text-center text-[#3b82f6] font-mono">{{ formatVolume(userBidOrder.quantity) }}</div>
        </div>

        <!-- Lag Heartbeat -->
        <div class="pt-0.5 lg:pt-0.5 md:pt-1 border-t border-[#2b3139] flex justify-between items-center">
          <span class="text-[10px] lg:text-[9px] md:text-xs text-gray-400">卡顿</span>
          <div class="flex items-center space-x-1 lg:space-x-0.5">
            <div class="flex space-x-0.5">
              <div v-for="i in 5" :key="i" :class="['w-0.5 lg:w-0.5 h-2 lg:h-1.5 md:h-2.5 rounded-sm', i <= binanceLagLevel ? 'bg-[#f6465d]' : 'bg-[#2b3139]']"></div>
            </div>
            <span
              @dblclick="resetBinanceLag"
              class="text-[10px] lg:text-[9px] md:text-xs font-mono cursor-pointer hover:text-[#f0b90b] transition-colors"
              title="双击清零"
            >{{ binanceLagCount }}</span>
          </div>
        </div>
      </div>

      <!-- Market Bottom Tabs: K线图 + 数据流 -->
      <div class="mt-1 bg-[#252930] rounded border border-[#2b3139]">
        <div class="flex border-b border-[#2b3139]">
          <button @click="bottomTab = 'kline'" :class="['flex-1 px-2 py-1 text-xs font-medium transition-colors', bottomTab === 'kline' ? 'text-[#f0b90b] border-b-2 border-[#f0b90b] bg-[#1e2329]' : 'text-gray-400 hover:text-white']">K线图</button>
          <button @click="bottomTab = 'stream'" :class="['flex-1 px-2 py-1 text-xs font-medium transition-colors', bottomTab === 'stream' ? 'text-[#f0b90b] border-b-2 border-[#f0b90b] bg-[#1e2329]' : 'text-gray-400 hover:text-white']">数据流</button>
        </div>
        <MiniKlineChart v-show="bottomTab === 'kline'" :visible="bottomTab === 'kline'" />
        <div v-show="bottomTab === 'stream'">
          <SpreadDataTable />
        </div>
      </div>

      <!-- Pending Orders Modal -->
      <div v-if="showModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click="closeModal">
        <div class="bg-[#1e2329] rounded-lg p-6 max-w-4xl w-full mx-4 max-h-[80vh] overflow-auto" @click.stop>
          <div class="flex justify-between items-center mb-4">
            <h3 class="text-xl font-bold text-white">{{ modalType === 'ASK' ? 'ASK挂单' : 'BID挂单' }}</h3>
            <button @click="closeModal" class="text-gray-400 hover:text-white text-2xl">&times;</button>
          </div>

          <div v-if="pendingOrders.length === 0" class="text-center text-gray-400 py-8">
            暂无挂单
          </div>

          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-[#2b3139]">
                  <th class="text-left py-2 px-3 text-gray-400">交易所</th>
                  <th class="text-left py-2 px-3 text-gray-400">方向</th>
                  <th class="text-right py-2 px-3 text-gray-400">价格</th>
                  <th class="text-right py-2 px-3 text-gray-400">数量</th>
                  <th class="text-right py-2 px-3 text-gray-400">已成交</th>
                  <th class="text-left py-2 px-3 text-gray-400">状态</th>
                  <th class="text-left py-2 px-3 text-gray-400">时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="order in pendingOrders" :key="order.id" class="border-b border-[#2b3139] hover:bg-[#2b3139]">
                  <td class="py-2 px-3 text-white">{{ order.exchange }}</td>
                  <td class="py-2 px-3">
                    <span :class="order.side === 'buy' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                      {{ order.side === 'buy' ? '买入' : '卖出' }}
                    </span>
                  </td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.price?.toFixed(2) || '-' }}</td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ order.quantity?.toFixed(4) || '-' }}</td>
                  <td class="py-2 px-3 text-right text-white font-mono">{{ (order.executed_qty ?? order.cum_exec_qty)?.toFixed(4) || '0' }}</td>
                  <td class="py-2 px-3 text-white">{{ order.status || order.order_status }}</td>
                  <td class="py-2 px-3 text-gray-400 text-xs">{{ formatTime(order.timestamp || order.created_time) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      </div>
    </div>

    <!-- System Status Modal -->
    <SystemStatusModal :isOpen="showSystemStatusModal" @close="showSystemStatusModal = false" />
  </div>

    <!-- Liquidation Danger Notification Overlay (non-blocking) -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="liqNotification"
          class="fixed top-4 right-4 z-[9999] bg-[#ff0000]/95 text-white rounded-lg shadow-2xl p-4 max-w-sm cursor-pointer border-2 border-[#ff4444] liq-flash"
          @click="liqNotification = null">
          <div class="font-bold text-sm mb-1">⚠️ 市场接近危险！</div>
          <div class="text-xs space-y-0.5">
            <div>{{ liqNotification.label }}距离市场价仅 {{ liqNotification.pct }}%</div>
            <div>当前价: {{ liqNotification.price }} | 强平价: {{ liqNotification.liq }}</div>
            <div class="text-[10px] text-white/70 mt-1">点击关闭 | 10秒后自动消失</div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'
import { useProxyStore } from '@/stores/proxy'
import { PlatformId, isHedge } from '@/constants/platform'
import { useStrategyStore } from '@/stores/strategy'
import SystemStatusModal from '@/components/SystemStatusModal.vue'
import api from '@/services/api'
import SpreadDataTable from './SpreadDataTable.vue'
import MiniKlineChart from './MiniKlineChart.vue'
import { useTradingPair } from '@/composables/useTradingPair'

const bottomTab = ref("kline")
const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const { currentPair, pairConfig } = useTradingPair()
const proxyStore = useProxyStore()
const strategyStore = useStrategyStore()

// System Status Modal
const showSystemStatusModal = ref(false)
const systemStatusText = ref('系统正常运行')
const systemHealthy = ref(true)
const redisStatus = ref({ healthy: false, last_error: null })

// Market close status
const marketOpen = ref(true)
const marketWarning = ref(false)
const marketMessage = ref('')
let marketStatusTimer = null

async function checkMarketStatus() {
  try {
    const r = await api.get('/api/v1/system/market-status')
    const d = r.data
    marketOpen.value = d.is_open !== false
    marketMessage.value = d.message || ''
    marketWarning.value = marketOpen.value && marketMessage.value.includes('即将休市')
  } catch { /* silent */ }
}
const sslCertStatus = ref({ status: 'unknown', days_remaining: 0 })
const proxyHealthStatus = ref({ total: 0, active: 0, failed: 0, avgHealth: 100 })

const bybitConnected = ref(false)
const binanceConnected = ref(false)

const bybit = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })
const binance = ref({ bid: 0, ask: 0, mid: 0, prevBid: 0, prevAsk: 0, prevMid: 0 })

// 当前产品对的强平价（按 pair_code 隔离）
const currentLiq = computed(() => {
  const v = strategyStore.getLiquidationPrices(currentPair.value)
  return v
})

// Fallback: fetch liq prices directly if store is empty after 3s
const _liqFallbackDone = ref(false)
async function _fetchLiqDirect() {
  try {
    const resp = await api.get('/api/v1/accounts/dashboard/aggregated')
    const accounts = resp.data?.accounts || []
    console.log('[LIQ_FALLBACK] fetched', accounts.length, 'accounts')
    // Group by pair_code and populate store
    const { PlatformId, isHedge } = await import('@/constants/platform')
    const pairGroups = {}
    for (const acc of accounts) {
      if (acc.error || !acc.balance) continue
      const b = acc.balance
      const pairCode = acc.pair_code
      if (!pairCode) continue
      if (!pairGroups[pairCode]) {
        pairGroups[pairCode] = { binance: { long: null, short: null }, mt5: { long: null, short: null } }
      }
      const pg = pairGroups[pairCode]
      const isBinance = acc.platform_id === PlatformId.BINANCE
      const isMT5 = acc.is_mt5_account && isHedge(acc.platform_id)
      if (isBinance || isMT5) {
        const longLiq = b.long_liquidation_price > 0 ? b.long_liquidation_price : null
        const shortLiq = b.short_liquidation_price > 0 ? b.short_liquidation_price : null
        const slot = isBinance ? pg.binance : pg.mt5
        if (longLiq && (!slot.long || longLiq > slot.long)) slot.long = longLiq
        if (shortLiq && (!slot.short || shortLiq < slot.short)) slot.short = shortLiq
      }
    }
    for (const [pairCode, pg] of Object.entries(pairGroups)) {
      console.log('[LIQ_FALLBACK] writing', pairCode, JSON.stringify(pg))
      strategyStore.setLiquidationPrices(pairCode, 'binance', pg.binance.long, pg.binance.short)
      strategyStore.setLiquidationPrices(pairCode, 'mt5', pg.mt5.long, pg.mt5.short)
    }
    _liqFallbackDone.value = true
  } catch (e) {
    console.error('[LIQ_FALLBACK] error:', e)
  }
}

// If store is empty after 3 seconds, fetch directly
setTimeout(() => {
  const keys = Object.keys(strategyStore.liquidationPrices)
  if (keys.length === 0 && !_liqFallbackDone.value) {
    console.log('[LIQ_FALLBACK] store empty after 3s, fetching directly')
    _fetchLiqDirect()
  }
}, 3000)

// Liquidation proximity danger detection (默认 1.5%, 可通过 risk_settings 自定义)
const LIQ_DANGER_PCT = 0.015
const liqAlertShown = ref({})

function isLiqDanger(liqPrice, marketPrice) {
  if (!liqPrice || !marketPrice || liqPrice <= 0 || marketPrice <= 0) return false
  return Math.abs(marketPrice - liqPrice) / marketPrice < LIQ_DANGER_PCT
}

const liqDanger = computed(() => ({
  binanceLong:  isLiqDanger(currentLiq.value.binance.long, binance.value.mid),
  binanceShort: isLiqDanger(currentLiq.value.binance.short, binance.value.mid),
  mt5Long:      isLiqDanger(currentLiq.value.mt5.long, bybit.value.mid),
  mt5Short:     isLiqDanger(currentLiq.value.mt5.short, bybit.value.mid),
}))

function liqDistPct(liqPrice, marketPrice) {
  if (!liqPrice || !marketPrice || marketPrice <= 0) return null
  return ((Math.abs(marketPrice - liqPrice) / marketPrice) * 100).toFixed(2)
}

// 强平危险时：跑马灯闪烁 + 非阻塞通知
const liqDangerActive = computed(() =>
  liqDanger.value.binanceLong || liqDanger.value.binanceShort ||
  liqDanger.value.mt5Long || liqDanger.value.mt5Short
)

const liqDangerText = computed(() => {
  const parts = []
  const liq = currentLiq.value
  if (liqDanger.value.binanceLong)
    parts.push('主账号多强平距离 ' + liqDistPct(liq.binance.long, binance.value.mid) + '%')
  if (liqDanger.value.binanceShort)
    parts.push('主账号空强平距离 ' + liqDistPct(liq.binance.short, binance.value.mid) + '%')
  if (liqDanger.value.mt5Long)
    parts.push('对冲多强平距离 ' + liqDistPct(liq.mt5.long, bybit.value.mid) + '%')
  if (liqDanger.value.mt5Short)
    parts.push('对冲空强平距离 ' + liqDistPct(liq.mt5.short, bybit.value.mid) + '%')
  return parts.length ? '⚠ ' + currentPair.value + ' ' + parts.join(' | ') : ''
})

// ── 行情背离软暂停状态（后端 QuoteDivergenceMonitor 广播）──
const quoteDivergence = computed(() => marketStore.quoteDivergence)
const quoteDiverged = computed(() => quoteDivergence.value?.diverged === true)
const quoteRecoveredFlash = ref(false)
let quoteRecoverTimer = null
watch(quoteDiverged, (now, prev) => {
  if (prev === true && now === false) {
    quoteRecoveredFlash.value = true
    if (quoteRecoverTimer) clearTimeout(quoteRecoverTimer)
    quoteRecoverTimer = setTimeout(() => { quoteRecoveredFlash.value = false }, 5000)
  }
})

const marqueeText = computed(() => {
  const parts = []
  if (quoteDiverged.value) {
    const d = quoteDivergence.value
    parts.push(`⛔ 行情背离 ICMarkets ${d?.ic ?? '-'} vs Bybit ${d?.ref ?? '-'} 差价 ${(d?.diff ?? 0).toFixed(2)}（已暂停下单）`)
  } else if (quoteRecoveredFlash.value) {
    parts.push(`✓ 行情已恢复（差价 ${(quoteDivergence.value?.diff ?? 0).toFixed(2)}），已继续运行`)
  }
  if (liqDangerActive.value) parts.push(liqDangerText.value)
  if (!marketOpen.value && marketMessage.value) parts.push('⛔ ' + marketMessage.value)
  else if (marketWarning.value && marketMessage.value) parts.push('⚠ ' + marketMessage.value)
  parts.push(systemStatusText.value)
  return parts.join(' | ')
})

const marqueeColorClass = computed(() => {
  if (quoteDiverged.value) return 'text-[#ff0000] liq-flash font-bold'
  if (quoteRecoveredFlash.value) return 'text-[#0ecb81] font-bold'
  if (liqDangerActive.value) return 'text-[#ff0000] liq-flash font-bold'
  if (!marketOpen.value) return 'text-[#f6465d] font-bold'
  if (marketWarning.value) return 'text-[#f0b90b] font-bold'
  if (!systemHealthy.value) return 'text-[#f6465d]'
  return 'text-[#0ecb81]'
})

const marqueeButtonBg = computed(() => {
  if (quoteDiverged.value) return 'bg-[#ff0000]/20 hover:bg-[#ff0000]/30'
  if (quoteRecoveredFlash.value) return 'bg-[#0ecb81]/20 hover:bg-[#0ecb81]/30'
  if (liqDangerActive.value) return 'bg-[#ff0000]/20 hover:bg-[#ff0000]/30'
  if (!marketOpen.value) return 'bg-[#f6465d]/20 hover:bg-[#f6465d]/30'
  if (marketWarning.value) return 'bg-[#f0b90b]/20 hover:bg-[#f0b90b]/30'
  if (!systemHealthy.value) return 'bg-[#f6465d]/20 hover:bg-[#f6465d]/30'
  return 'bg-[#0ecb81]/20 hover:bg-[#0ecb81]/30'
})

// Non-blocking notification overlay for liq danger
const liqNotification = ref(null)

watch(liqDanger, (d) => {
  const checks = [
    { key: 'binanceLong',  danger: d.binanceLong,  label: '主账号多头强平价', liq: currentLiq.value.binance.long, price: binance.value.mid },
    { key: 'binanceShort', danger: d.binanceShort, label: '主账号空头强平价', liq: currentLiq.value.binance.short, price: binance.value.mid },
    { key: 'mt5Long',      danger: d.mt5Long,      label: '对冲账号多头强平价', liq: currentLiq.value.mt5.long, price: bybit.value.mid },
    { key: 'mt5Short',     danger: d.mt5Short,     label: '对冲账号空头强平价', liq: currentLiq.value.mt5.short, price: bybit.value.mid },
  ]
  for (const c of checks) {
    if (c.danger && !liqAlertShown.value[c.key]) {
      liqAlertShown.value[c.key] = true
      const pct = liqDistPct(c.liq, c.price)
      liqNotification.value = {
        label: c.label,
        pct: pct,
        price: c.price?.toFixed(2),
        liq: c.liq?.toFixed(2),
      }
      setTimeout(() => { liqNotification.value = null }, 10000)
    } else if (!c.danger) {
      liqAlertShown.value[c.key] = false
    }
  }
}, { deep: true })

// Lag detection with sliding window (last 60 seconds)
const SLIDING_WINDOW_SIZE = 60 // 60 seconds
const LAG_THRESHOLD = 2000 // 2 seconds
const bybitUpdateTimestamps = ref([]) // Store last N update timestamps
const binanceUpdateTimestamps = ref([]) // Store last N update timestamps
const dataAlive = ref(false)
let _dataAliveTimer = null
let lastUpdateTime = Date.now()
let lagTimer = null

// Computed lag count based on sliding window
const bybitLagCount = computed(() => {
  const now = Date.now()
  const windowStart = now - SLIDING_WINDOW_SIZE * 1000

  // Remove old timestamps outside the window
  const recentTimestamps = bybitUpdateTimestamps.value.filter(t => t > windowStart)

  // Count gaps > LAG_THRESHOLD
  let lagCount = 0
  for (let i = 1; i < recentTimestamps.length; i++) {
    if (recentTimestamps[i] - recentTimestamps[i - 1] > LAG_THRESHOLD) {
      lagCount++
    }
  }

  // Check if current time has a lag
  if (recentTimestamps.length > 0 && now - recentTimestamps[recentTimestamps.length - 1] > LAG_THRESHOLD) {
    lagCount++
  }

  return lagCount
})

const binanceLagCount = computed(() => {
  const now = Date.now()
  const windowStart = now - SLIDING_WINDOW_SIZE * 1000

  // Remove old timestamps outside the window
  const recentTimestamps = binanceUpdateTimestamps.value.filter(t => t > windowStart)

  // Count gaps > LAG_THRESHOLD
  let lagCount = 0
  for (let i = 1; i < recentTimestamps.length; i++) {
    if (recentTimestamps[i] - recentTimestamps[i - 1] > LAG_THRESHOLD) {
      lagCount++
    }
  }

  // Check if current time has a lag
  if (recentTimestamps.length > 0 && now - recentTimestamps[recentTimestamps.length - 1] > LAG_THRESHOLD) {
    lagCount++
  }

  return lagCount
})

// Pending orders data
const askOrderCount = ref(0)
const bidOrderCount = ref(0)
// 用户自己的最新一笔 Binance 挂单 (取价格最优的那笔)
const userAskOrder = ref({ price: 0, quantity: 0 })
const userBidOrder = ref({ price: 0, quantity: 0 })
const showModal = ref(false)
const modalType = ref('') // 'ASK' or 'BID'
const pendingOrders = ref([])
let orderFetchTimer = null

// Order book data
const bybitOrderBook = ref({ bid_price: 0, bid_volume: 0, ask_price: 0, ask_volume: 0 })
const binanceOrderBook = ref({ bid_price: 0, bid_volume: 0, ask_price: 0, ask_volume: 0 })
let orderBookFetchTimer = null

// Profit and position data
const forwardActualPosition = ref(0)
const reverseActualPosition = ref(0)

// 后端已算好的账户余额缓存（含 unrealized_pnl）
// 由 fetchAccountData / handleAccountBalanceUpdate 更新
// key: platform_id，同平台多账户的 unrealized_pnl 会累加
const accountsBalanceByPlatform = ref({})  // { 1: {unrealized_pnl: sum}, 2: ..., 4: ..., 5: ... }

// Position spread data - store position details for cost calculation
const binanceShortPositions = ref([]) // Binance SHORT positions
const binanceLongPositions = ref([]) // Binance LONG positions
const bybitShortPositions = ref([]) // Bybit SHORT positions
const bybitLongPositions = ref([]) // Bybit LONG positions

// Computed position totals
const binanceLongTotal = computed(() => {
  return binanceLongPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})
const binanceShortTotal = computed(() => {
  return binanceShortPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})
const bybitLongTotal = computed(() => {
  return bybitLongPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})
const bybitShortTotal = computed(() => {
  return bybitShortPositions.value.reduce((sum, pos) => sum + (pos.size || 0), 0)
})

// Fee data
const bybitLongSwapFee = ref(0)
const bybitShortSwapFee = ref(0)
let bybitSwapRateTimer = null

// WS-pushed market rates (10s interval from MarketRateStreamer)
watch(() => marketStore.marketRates, (rates) => {
  if (!rates) return
  if (rates.funding) {
    binanceLongFundingRate.value = rates.funding.long_cost_per_lot ?? 0
    binanceShortFundingRate.value = rates.funding.short_cost_per_lot ?? 0
    binanceFundingRatePct.value = rates.funding.funding_rate_pct ?? 0
    binanceNextFundingTime.value = rates.funding.next_funding_time ?? 0
  }
  if (rates.swap) {
    bybitLongSwapFee.value = rates.swap.long_swap_per_lot ?? 0
    bybitShortSwapFee.value = rates.swap.short_swap_per_lot ?? 0
  }
}, { deep: true })

// 主账户资金费 = 持仓量(XAU) / 100 * cost_per_lot
const mainFundingFee = computed(() => {
  const longFee = (binanceLongTotal.value / 100) * binanceLongFundingRate.value
  const shortFee = (binanceShortTotal.value / 100) * binanceShortFundingRate.value
  return longFee + shortFee
})

// 对冲过夜费 = 持仓手数 * swap_per_lot
const hedgeOvernightFee = computed(() => {
  const longFee = bybitLongTotal.value * bybitLongSwapFee.value
  const shortFee = bybitShortTotal.value * bybitShortSwapFee.value
  return longFee + shortFee
})
// Binance real-time funding rate (per lot = 100 XAU)
const binanceLongFundingRate = ref(0)   // long_cost_per_lot: >0 long pays, <0 long receives
const binanceShortFundingRate = ref(0)  // short_cost_per_lot: opposite sign
const binanceFundingRatePct = ref(0)    // raw rate percentage for display
const binanceNextFundingTime = ref(0)   // next settlement timestamp ms
let fundingRateTimer = null

// USD/USDT exchange rate
const usdToUsdtRate = ref(1.0)
let exchangeRateTimer = null

const bybitLagLevel = computed(() => Math.min(Math.floor(bybitLagCount.value / 10), 5))
const binanceLagLevel = computed(() => Math.min(Math.floor(binanceLagCount.value / 10), 5))

// Calculate reverse spread: Binance SHORT cost - Bybit LONG cost
const reverseSpread = computed(() => {
  if (binanceShortPositions.value.length === 0 || bybitLongPositions.value.length === 0) {
    return 0
  }

  // Calculate Binance SHORT average cost price
  const binanceShortCost = binanceShortPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const binanceShortSize = binanceShortPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const binanceShortAvg = binanceShortSize > 0 ? binanceShortCost / binanceShortSize : 0

  // Calculate Bybit LONG average cost price
  const bybitLongCost = bybitLongPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const bybitLongSize = bybitLongPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const bybitLongAvg = bybitLongSize > 0 ? bybitLongCost / bybitLongSize : 0

  // Reverse spread = Binance SHORT cost - Bybit LONG cost
  return binanceShortAvg - bybitLongAvg
})

// Calculate forward spread: Bybit SHORT cost - Binance LONG cost
const forwardSpread = computed(() => {
  if (bybitShortPositions.value.length === 0 || binanceLongPositions.value.length === 0) {
    return 0
  }

  // Calculate Bybit SHORT average cost price
  const bybitShortCost = bybitShortPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const bybitShortSize = bybitShortPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const bybitShortAvg = bybitShortSize > 0 ? bybitShortCost / bybitShortSize : 0

  // Calculate Binance LONG average cost price
  const binanceLongCost = binanceLongPositions.value.reduce((sum, pos) => {
    return sum + (pos.entry_price * pos.size)
  }, 0)
  const binanceLongSize = binanceLongPositions.value.reduce((sum, pos) => sum + pos.size, 0)
  const binanceLongAvg = binanceLongSize > 0 ? binanceLongCost / binanceLongSize : 0

  // Forward spread = Bybit SHORT cost - Binance LONG cost
  return bybitShortAvg - binanceLongAvg
})

// Calculate Binance floating profit (USDT)
// 优先使用后端已算好的 unrealized_pnl（来自 Binance totalUnrealizedProfit）
// 后端 balance.unrealized_pnl 即为 Binance 账户当前持仓实时浮动盈亏（USDT）
const binanceFloatingProfit = computed(() => {
  const b = accountsBalanceByPlatform.value[1]
  if (b && b.unrealized_pnl != null) return parseFloat(b.unrealized_pnl)

  // fallback：用仓位数据估算（仅在后端数据未到达时）
  let profit = 0
  binanceLongPositions.value.forEach(pos => {
    const markPrice = binance.value.mid || pos.mark_price
    profit += (markPrice - pos.entry_price) * pos.size
  })
  binanceShortPositions.value.forEach(pos => {
    const markPrice = binance.value.mid || pos.mark_price
    profit += (pos.entry_price - markPrice) * pos.size
  })
  return profit
})

// Calculate Bybit/MT5 floating profit (USDT)
// 优先使用后端已算好的 unrealized_pnl（= equity - balance，MT5 终端"盈亏"列）
// 后端已处理合约乘数和 USD→USDT 汇率换算，直接使用，无需前端重算
const bybitFloatingProfit = computed(() => {
  const b = accountsBalanceByPlatform.value[2]
  if (b && b.unrealized_pnl != null) return parseFloat(b.unrealized_pnl)

  // fallback：用仓位数据估算（仅在后端数据未到达时，注意汇率可能有偏差）
  let profitUSD = 0
  bybitLongPositions.value.forEach(pos => {
    const markPrice = bybit.value.mid || pos.mark_price
    profitUSD += (markPrice - pos.entry_price) * pos.size
  })
  bybitShortPositions.value.forEach(pos => {
    const markPrice = bybit.value.mid || pos.mark_price
    profitUSD += (pos.entry_price - markPrice) * pos.size
  })
  return profitUSD * usdToUsdtRate.value
})

// 总盈利 = 全平台实时浮动盈亏之和
// 包含 Binance(1) + Bybit/MT5(2) + IC Markets(3) + Gate.io(4) + OKX(5)
const totalProfit = computed(() => {
  let sum = binanceFloatingProfit.value + bybitFloatingProfit.value
  for (const pid of [3, 4, 5]) {
    const b = accountsBalanceByPlatform.value[pid]
    if (b && b.unrealized_pnl != null) sum += parseFloat(b.unrealized_pnl)
  }
  return sum
})

watch(() => marketStore.marketData, (data) => {
  if (!data) return

  const now = Date.now()

  // Add timestamp to sliding window
  bybitUpdateTimestamps.value.push(now)
  binanceUpdateTimestamps.value.push(now)

  // Keep only recent timestamps (last 60 seconds + buffer)
  const windowStart = now - (SLIDING_WINDOW_SIZE + 10) * 1000
  bybitUpdateTimestamps.value = bybitUpdateTimestamps.value.filter(t => t > windowStart)
  binanceUpdateTimestamps.value = binanceUpdateTimestamps.value.filter(t => t > windowStart)

  lastUpdateTime = now
  dataAlive.value = true
  clearTimeout(_dataAliveTimer)
  _dataAliveTimer = setTimeout(() => { dataAlive.value = false }, 300)

  // Only update if values actually changed
  const bybitBidChanged = bybit.value.bid !== (data.bybit_bid || 0)
  const bybitAskChanged = bybit.value.ask !== (data.bybit_ask || 0)
  const binanceBidChanged = binance.value.bid !== (data.binance_bid || 0)
  const binanceAskChanged = binance.value.ask !== (data.binance_ask || 0)

  if (bybitBidChanged || bybitAskChanged || binanceBidChanged || binanceAskChanged) {
    bybit.value.prevBid = bybit.value.bid
    bybit.value.prevAsk = bybit.value.ask
    bybit.value.prevMid = bybit.value.mid
    binance.value.prevBid = binance.value.bid
    binance.value.prevAsk = binance.value.ask
    binance.value.prevMid = binance.value.prevMid

    bybit.value.bid = data.bybit_bid || 0
    bybit.value.ask = data.bybit_ask || 0
    bybit.value.mid = data.bybit_mid || ((bybit.value.bid + bybit.value.ask) / 2)

    binance.value.bid = data.binance_bid || 0
    binance.value.ask = data.binance_ask || 0
    binance.value.mid = data.binance_mid || ((binance.value.bid + binance.value.ask) / 2)

    bybitConnected.value = true
    binanceConnected.value = true

    // Update order book from WS data (volume from bookTicker)
    if (data.binance_bid_qty != null || data.binance_ask_qty != null) {
      binanceOrderBook.value = {
        bid_price: data.binance_bid || 0,
        bid_volume: data.binance_bid_qty || 0,
        ask_price: data.binance_ask || 0,
        ask_volume: data.binance_ask_qty || 0,
      }
    }
    if (data.bybit_bid_qty != null || data.bybit_ask_qty != null) {
      bybitOrderBook.value = {
        bid_price: data.bybit_bid || 0,
        bid_volume: data.bybit_bid_qty || 0,
        ask_price: data.bybit_ask || 0,
        ask_volume: data.bybit_ask_qty || 0,
      }
    }
  }
}, { deep: false }) // Shallow watch for better performance

// Watch global pair selection — refresh all market data when pair changes
watch(currentPair, () => {
  fetchOrderBook()
  fetchBinanceFundingRate()
  fetchBybitSwapRate()
})

watch(() => marketStore.connected, (val) => {
  if (!val) {
    bybitConnected.value = false
    binanceConnected.value = false
  }
}, { deep: false })

// Watch for account balance and misc WebSocket messages (NOT position_snapshot)
watch(() => marketStore.lastMessage, (message) => {
  if (!message) return
  if (message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  } else if (message.type === 'redis_status') {
    redisStatus.value = message.data
  }
}, { deep: false })

// Position data: watch the deduped positionSnapshot (same source as StrategyPanel)
watch(() => marketStore.positionSnapshot, (snap) => {
  if (snap) handlePositionSnapshot(snap)
}, { deep: false })

// position_snapshot: real-time data pushed immediately after a trade fill.
// Atomically replaces both Bybit and Binance positions — no intermediate zero state, no flash.
function handlePositionSnapshot(data) {
  if (!data) return
  const pairData = data.pairs?.[currentPair.value]
  const longLots = pairData ? (pairData.mt5_long ?? 0) : (data.bybit_long_lots ?? 0)
  const shortLots = pairData ? (pairData.mt5_short ?? 0) : (data.bybit_short_lots ?? 0)
  const binanceLong = pairData ? (pairData.binance_long ?? 0) : (data.binance_long_xau ?? 0)
  const binanceShort = pairData ? (pairData.binance_short ?? 0) : (data.binance_short_xau ?? 0)

  // Anti-flicker: skip all-zero if we currently hold positions
  const incomingAllZero = (longLots === 0 && shortLots === 0 && binanceLong === 0 && binanceShort === 0)
  const currentHasPosition = (bybitLongTotal.value !== 0 || bybitShortTotal.value !== 0 ||
                              binanceLongTotal.value !== 0 || binanceShortTotal.value !== 0)
  if (incomingAllZero && currentHasPosition) return

  // Dedup: only update refs when values actually change (prevents unnecessary re-renders)
  const newBL = longLots > 0 ? longLots : 0
  const newBS = shortLots > 0 ? shortLots : 0
  const newCL = binanceLong > 0 ? binanceLong : 0
  const newCS = binanceShort > 0 ? binanceShort : 0
  if (bybitLongTotal.value !== newBL) bybitLongPositions.value = newBL > 0 ? [{ size: newBL }] : []
  if (bybitShortTotal.value !== newBS) bybitShortPositions.value = newBS > 0 ? [{ size: newBS }] : []
  if (binanceLongTotal.value !== newCL) binanceLongPositions.value = newCL > 0 ? [{ size: newCL }] : []
  if (binanceShortTotal.value !== newCS) binanceShortPositions.value = newCS > 0 ? [{ size: newCS }] : []
}

function handleAccountBalanceUpdate(data) {
  console.log('[handleAccountBalanceUpdate] Received data:', {
    accountsCount: data.accounts?.length,
    positionsCount: data.positions?.length,
    positions: data.positions
  })

  // 缓存各平台余额 unrealized_pnl，供 totalProfit 计算使用
  // 同平台多账户的 unrealized_pnl 累加，确保 Gate/OKX 等也计入
  if (data.accounts && data.accounts.length > 0) {
    const newBalances = {}
    data.accounts.forEach(acc => {
      if (acc.balance && acc.platform_id) {
        const pid = acc.platform_id
        if (!newBalances[pid]) {
          newBalances[pid] = { ...acc.balance }
        } else {
          newBalances[pid].unrealized_pnl = (newBalances[pid].unrealized_pnl || 0) + (acc.balance.unrealized_pnl || 0)
        }
      }
    })
    accountsBalanceByPlatform.value = newBalances
  }

  // Extract fee data from accounts
  if (data.accounts && data.accounts.length > 0) {
    // Note: bybitLongSwapFee / bybitShortSwapFee are now fetched in real-time
    // via fetchBybitSwapRate() polling — do NOT overwrite them here.

    // Reset position values
    forwardActualPosition.value = 0
    reverseActualPosition.value = 0

    // Get first account's positions and aggregate fees from all accounts
    const bybitAccounts = data.accounts.filter(acc => isHedge(acc.platform_id))
    const binanceAccounts = data.accounts.filter(acc => acc.platform_id === PlatformId.BINANCE)

    // Use first account's total_positions instead of aggregating
    if (bybitAccounts.length > 0) {
      reverseActualPosition.value = bybitAccounts[0].balance?.total_positions || 0
    }
    if (binanceAccounts.length > 0) {
      forwardActualPosition.value = binanceAccounts[0].balance?.total_positions || 0
    }

    // Aggregate fees from all accounts
    data.accounts.forEach(account => {
      if (isHedge(account.platform_id)) {
        // Bybit swap rate is now fetched in real-time via fetchBybitSwapRate()
        // Binance funding rate is fetched in real-time via fetchBinanceFundingRate()
      }
    })
  }

  // Extract actual positions from positions array for spread calculation
  if (data.positions && data.positions.length > 0) {
    // Build new arrays first, then atomically swap — prevents flash-to-zero
    const newBinanceLong = []
    const newBinanceShort = []
    const newBybitLong = []
    const newBybitShort = []

    data.positions.forEach(position => {
      const account = data.accounts?.find(acc => acc.account_id === position.account_id)
      if (!account) return

      // Backend schema (AccountPosition): side / size / entry_price / mark_price / unrealized_pnl
      const posData = {
        size: Math.abs(position.size || 0),
        entry_price: position.entry_price || 0,
        mark_price: position.mark_price || 0
      }

      if (isHedge(account.platform_id)) {
        if (position.side === 'Buy') newBybitLong.push(posData)
        else if (position.side === 'Sell') newBybitShort.push(posData)
      } else if (account.platform_id === PlatformId.BINANCE) {
        if (position.side === 'Buy') newBinanceLong.push(posData)
        else if (position.side === 'Sell') newBinanceShort.push(posData)
      }
    })

    // Atomic swap — all four refs update in the same microtask, no intermediate empty state
    binanceLongPositions.value = newBinanceLong
    binanceShortPositions.value = newBinanceShort
    bybitLongPositions.value = newBybitLong
    bybitShortPositions.value = newBybitShort
  }
  // Note: If positions is empty or undefined, keep existing position arrays unchanged
}

onMounted(() => {
  marketStore.connect()

  // Initialize timestamps with current time
  const now = Date.now()
  bybitUpdateTimestamps.value = [now]
  binanceUpdateTimestamps.value = [now]
  lastUpdateTime = now

  // No longer need lagTimer as we use sliding window

  // Fetch initial position data immediately on page load (prevents 0.00 display until WebSocket update)
  fetchAccountData()
  // Position data is then kept up-to-date via WebSocket (account_balance / position_snapshot)
  fetchPendingOrderCounts()
  fetchOrderBook()
  fetchRedisStatus()
  fetchSSLCertStatus()
  fetchProxyHealthStatus()
  fetchExchangeRate()
  fetchBinanceFundingRate()
  checkMarketStatus()

  // Fetch pending order counts every 3 seconds
  orderFetchTimer = setInterval(() => {
    fetchPendingOrderCounts()
  }, 3000)

  // Order book now updated via WebSocket (market_data messages)
  // REST fetchOrderBook kept as one-shot initial load only

  // Fetch exchange rate every 10 minutes
  exchangeRateTimer = setInterval(() => {
    fetchExchangeRate()
  }, 600000)

  // Fetch Binance funding rate every 30 seconds
  fundingRateTimer = setInterval(() => {
    fetchBinanceFundingRate()
  }, 30000)

  // Fetch Bybit swap rate every 60 seconds (changes infrequently)
  fetchBybitSwapRate()
  bybitSwapRateTimer = setInterval(() => {
    fetchBybitSwapRate()
  }, 60000)

  // Check market status every 60 seconds
  marketStatusTimer = setInterval(checkMarketStatus, 60000)

  // 初始化系统状态并开始轮询
  updateSystemStatus()
  const statusInterval = setInterval(updateSystemStatus, 10000)
  const proxyHealthInterval = setInterval(fetchProxyHealthStatus, 30000) // 每30秒刷新代理健康状态
  onUnmounted(() => {
    clearInterval(statusInterval)
    clearInterval(proxyHealthInterval)
  })
})

onUnmounted(() => {
  if (quoteRecoverTimer) clearTimeout(quoteRecoverTimer)
  if (lagTimer) clearInterval(lagTimer)
  if (orderFetchTimer) clearInterval(orderFetchTimer)
  // orderBookFetchTimer removed — orderbook now via WS
  if (exchangeRateTimer) clearInterval(exchangeRateTimer)
  if (fundingRateTimer) clearInterval(fundingRateTimer)
  if (bybitSwapRateTimer) clearInterval(bybitSwapRateTimer)
  if (marketStatusTimer) clearInterval(marketStatusTimer)
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

// Reset lag count by clearing timestamp history
function resetBybitLag() {
  const now = Date.now()
  bybitUpdateTimestamps.value = [now]
  console.log('Bybit lag count reset')
}

function resetBinanceLag() {
  const now = Date.now()
  binanceUpdateTimestamps.value = [now]
  console.log('Binance lag count reset')
}

async function fetchAccountData() {
  try {
    const response = await api.get('/api/v1/accounts/dashboard/aggregated')
    const data = response.data

    // Extract fee data and positions from accounts
    if (data.accounts && data.accounts.length > 0) {
      // Note: bybitLongSwapFee / bybitShortSwapFee are now fetched in real-time
      // via fetchBybitSwapRate() polling — do NOT overwrite them here.

      // 缓存各平台余额 unrealized_pnl，供 totalProfit 计算使用
      // 同平台多账户的 unrealized_pnl 累加
      const newBalances = {}
      data.accounts.forEach(acc => {
        if (acc.balance && acc.platform_id) {
          const pid = acc.platform_id
          if (!newBalances[pid]) {
            newBalances[pid] = { ...acc.balance }
          } else {
            newBalances[pid].unrealized_pnl = (newBalances[pid].unrealized_pnl || 0) + (acc.balance.unrealized_pnl || 0)
          }
        }
      })
      accountsBalanceByPlatform.value = newBalances

      // Reset position values
      forwardActualPosition.value = 0
      reverseActualPosition.value = 0

      // Get first account's positions and aggregate fees from all accounts
      const bybitAccounts = data.accounts.filter(acc => isHedge(acc.platform_id))
      const binanceAccounts = data.accounts.filter(acc => acc.platform_id === PlatformId.BINANCE)

      // Use first account's total_positions instead of aggregating
      if (bybitAccounts.length > 0) {
        reverseActualPosition.value = bybitAccounts[0].balance?.total_positions || 0
      }
      if (binanceAccounts.length > 0) {
        forwardActualPosition.value = binanceAccounts[0].balance?.total_positions || 0
      }

      // Aggregate fees from all accounts
      data.accounts.forEach(account => {
        if (isHedge(account.platform_id)) {
          // Bybit swap rate is now fetched in real-time via fetchBybitSwapRate()
          // Binance funding rate is fetched in real-time via fetchBinanceFundingRate()
        }
      })
    }

    // Extract actual positions from positions array for spread calculation
    if (data.positions && data.positions.length > 0) {
      // Reset position arrays
      // Build new arrays atomically — prevents flash-to-zero during reset
      const newBinanceLong = []
      const newBinanceShort = []
      const newBybitLong = []
      const newBybitShort = []

      // Aggregate positions by platform and side
      data.positions.forEach(position => {
        // Find the account for this position to get platform_id
        const account = data.accounts?.find(acc => acc.account_id === position.account_id)
        if (!account) return

        // Backend schema (AccountPosition): side / size / entry_price / mark_price / unrealized_pnl
        const posData = {
          size: Math.abs(position.size || 0),
          entry_price: position.entry_price || 0,
          mark_price: position.mark_price || 0
        }

        if (isHedge(account.platform_id)) {
          if (position.side === 'Buy') newBybitLong.push(posData)
          else if (position.side === 'Sell') newBybitShort.push(posData)
        } else if (account.platform_id === PlatformId.BINANCE) {
          if (position.side === 'Buy') newBinanceLong.push(posData)
          else if (position.side === 'Sell') newBinanceShort.push(posData)
        }
      })

      // Atomic swap
      binanceLongPositions.value = newBinanceLong
      binanceShortPositions.value = newBinanceShort
      bybitLongPositions.value = newBybitLong
      bybitShortPositions.value = newBybitShort
    }
    // Note: If positions is empty or undefined, keep existing position arrays unchanged
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

async function fetchPendingOrderCounts() {
  try {
    const response = await api.get('/api/v1/trading/orders/realtime')
    const orders = response.data || []

    console.log('[fetchPendingOrderCounts] Fetched orders:', orders.length, orders)

    // Count ASK and BID orders (backend returns lowercase 'buy' and 'sell')
    const askCount = orders.filter(order => order.side === 'sell').length
    const bidCount = orders.filter(order => order.side === 'buy').length

    askOrderCount.value = askCount
    bidOrderCount.value = bidCount

    // 提取最新代表挂单 (ASK 取最低价, BID 取最高价 — 最贴近成交的那笔)
    const askOrders = orders.filter(o => o.side === 'sell' && o.price > 0)
    const bidOrders = orders.filter(o => o.side === 'buy' && o.price > 0)
    if (askOrders.length > 0) {
      const best = askOrders.reduce((a, b) => (a.price < b.price ? a : b))
      userAskOrder.value = { price: best.price || 0, quantity: best.quantity || 0 }
    } else {
      userAskOrder.value = { price: 0, quantity: 0 }
    }
    if (bidOrders.length > 0) {
      const best = bidOrders.reduce((a, b) => (a.price > b.price ? a : b))
      userBidOrder.value = { price: best.price || 0, quantity: best.quantity || 0 }
    } else {
      userBidOrder.value = { price: 0, quantity: 0 }
    }

    console.log('[fetchPendingOrderCounts] ASK count:', askCount, 'BID count:', bidCount)
  } catch (error) {
    console.error('Failed to fetch pending orders:', error)
  }
}

async function fetchOrderBook() {
  try {
    const response = await api.get('/api/v1/market/orderbook', {
      params: { pair_code: currentPair.value }
    })
    const data = response.data || {}

    // Update Bybit order book (MT5 volume in lots, 1 lot = 100 oz)
    if (data.bybit && data.bybit.bid_price) {
      bybitOrderBook.value = {
        bid_price: data.bybit.bid_price || 0,
        bid_volume: data.bybit.bid_volume || 0,
        ask_price: data.bybit.ask_price || 0,
        ask_volume: data.bybit.ask_volume || 0
      }
    }

    // Update Binance order book (volume in contracts, 1 contract = 1 oz)
    if (data.binance && data.binance.bid_price) {
      binanceOrderBook.value = {
        bid_price: data.binance.bid_price || 0,
        bid_volume: data.binance.bid_volume || 0,
        ask_price: data.binance.ask_price || 0,
        ask_volume: data.binance.ask_volume || 0
      }
    }
  } catch (error) {
    console.error('Failed to fetch order book:', error)
  }
}

async function showPendingOrdersModal(type) {
  try {
    const response = await api.get('/api/v1/trading/orders/realtime')
    const orders = response.data || []

    // Filter orders by type (backend returns lowercase 'buy' and 'sell')
    if (type === 'ASK') {
      pendingOrders.value = orders.filter(order => order.side === 'sell')
    } else {
      pendingOrders.value = orders.filter(order => order.side === 'buy')
    }

    modalType.value = type
    showModal.value = true
  } catch (error) {
    console.error('Failed to fetch pending orders:', error)
  }
}

function closeModal() {
  showModal.value = false
  pendingOrders.value = []
}

function formatTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatVolume(volume) {
  if (!volume || volume === 0) return '0'
  return volume.toFixed(2)
}

// System Status Update - 整合所有系统状态和服务状态
async function updateSystemStatus() {
  try {
    const response = await api.get('/api/v1/system/status')
    const data = response.data

    const statuses = []

    // WebSocket状态
    if (marketStore.connected) {
      statuses.push('WS已连接')
    } else {
      statuses.push('WS未连接')
    }

    // 数据库连接池状态
    if (data.dbPool) {
      const usage = Math.round((data.dbPool.active / data.dbPool.max) * 100)
      statuses.push(`DB连接池:${usage}%`)
    }

    // 后端服务状态
    if (data.backend) {
      statuses.push('后端API正常')
    }

    // 持仓监控状态
    if (data.positionMonitor) {
      statuses.push('持仓监控运行中')
    }

    // 策略管理状态
    if (data.strategyManager) {
      statuses.push('策略管理运行中')
    }

    // Binance连接状态
    if (data.binance) {
      statuses.push('Binance已连接')
    }

    // Bybit连接状态
    if (data.bybit) {
      statuses.push('Bybit已连接')
    }

    // MT5连接状态
    if (data.mt5) {
      statuses.push('MT5已连接')
    }

    // 飞书服务状态
    if (notificationStore.feishuServiceStatus) {
      statuses.push('飞书服务正常')
    } else {
      statuses.push('飞书服务异常')
    }

    // Redis状态
    if (redisStatus.value.healthy) {
      statuses.push('Redis正常')
    } else {
      statuses.push('Redis异常')
    }

    // SSL证书状态
    if (sslCertStatus.value.status === 'healthy') {
      statuses.push(`SSL证书正常(${sslCertStatus.value.days_remaining}天)`)
    } else if (sslCertStatus.value.status === 'warning') {
      statuses.push(`SSL证书即将过期(${sslCertStatus.value.days_remaining}天)`)
    } else if (sslCertStatus.value.status === 'critical' || sslCertStatus.value.status === 'expired') {
      statuses.push('SSL证书异常')
    }

    // 系统运行时间
    if (data.uptime) {
      statuses.push(`运行:${data.uptime}`)
    }

    // 代理健康状态
    if (proxyHealthStatus.value.total > 0) {
      const proxyStatus = `代理:${proxyHealthStatus.value.active}/${proxyHealthStatus.value.total}活跃`
      if (proxyHealthStatus.value.avgHealth < 50) {
        statuses.push(`⚠️${proxyStatus}(健康度:${proxyHealthStatus.value.avgHealth})`)
      } else if (proxyHealthStatus.value.failed > 0) {
        statuses.push(`${proxyStatus}(${proxyHealthStatus.value.failed}失败)`)
      } else {
        statuses.push(proxyStatus)
      }
    }

    systemStatusText.value = statuses.join(' | ') || '系统正常运行'

    // 判断系统健康状态
    const dbUsage = data.dbPool ? (data.dbPool.active / data.dbPool.max) : 0
    const sslHealthy = ['healthy', 'warning'].includes(sslCertStatus.value.status)
    // Proxy: no proxies configured = direct-connect, considered healthy
    const proxyHealthy = proxyHealthStatus.value.total === 0 ||
                         (proxyHealthStatus.value.avgHealth >= 50 && proxyHealthStatus.value.failed === 0)
    systemHealthy.value = data.backend &&
                          marketStore.connected &&
                          dbUsage < 0.8 &&
                          redisStatus.value.healthy &&
                          sslHealthy &&
                          proxyHealthy
  } catch (error) {
    systemStatusText.value = '无法获取系统状态'
    systemHealthy.value = false
  }
}

async function fetchRedisStatus() {
  try {
    // Use /monitor/status for Redis info (Python backend).
    const response = await api.get('/api/v1/monitor/status')
    const redis = response.data?.redis
    redisStatus.value = {
      healthy: redis?.connected === true,
      last_error: redis?.error || null
    }
  } catch (error) {
    console.error('Failed to fetch Redis status:', error)
    redisStatus.value = { healthy: false, last_error: 'Failed to fetch status' }
  }
}

async function fetchSSLCertStatus() {
  try {
    const response = await api.get('/api/v1/monitor/ssl/current')
    // /monitor/ssl/current returns {most_urgent: {status, days_remaining, ...}, certificates: [...]}
    const cert = response.data?.most_urgent || response.data
    if (cert && cert.is_valid !== undefined) {
      sslCertStatus.value = {
        status: cert.status || 'unknown',
        days_remaining: cert.days_remaining || 0
      }
    }
  } catch (error) {
    console.error('Failed to fetch SSL cert status:', error)
    sslCertStatus.value = { status: 'error', days_remaining: 0 }
  }
}

async function fetchProxyHealthStatus() {
  try {
    // Trailing slash required — nginx 301 redirects /proxies → /proxies/ and drops Authorization header
    const response = await api.get('/api/v1/proxies/')
    const proxies = Array.isArray(response.data) ? response.data : []

    const total = proxies.length
    const active = proxies.filter(p => p.status === 'active').length
    const failed = proxies.filter(p => p.status === 'failed').length

    // Average health score — default to 100 when no proxies (direct-connect = healthy)
    let avgHealth = 100
    if (total > 0) {
      const totalHealth = proxies.reduce((sum, p) => sum + (p.health_score || 0), 0)
      avgHealth = Math.round(totalHealth / total)
    }

    proxyHealthStatus.value = { total, active, failed, avgHealth }
  } catch (error) {
    console.error('Failed to fetch proxy health status:', error)
    // No proxies configured or fetch failed — assume direct-connect (healthy)
    proxyHealthStatus.value = { total: 0, active: 0, failed: 0, avgHealth: 100 }
  }
}

// Fetch USD/USDT exchange rate from Binance API
async function fetchExchangeRate() {
  try {
    // Use Binance public API to get USDT price relative to USD
    // We use USDC/USDT as a proxy since USDC ≈ USD
    const response = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT')
    const data = await response.json()

    if (data.price) {
      // USDC/USDT price represents how many USDT = 1 USDC (≈ 1 USD)
      // So USD/USDT rate = USDC/USDT rate
      usdToUsdtRate.value = parseFloat(data.price)
      console.log('USD/USDT exchange rate updated:', usdToUsdtRate.value)
    }
  } catch (error) {
    console.error('Failed to fetch exchange rate, using default 1.0:', error)
    // Fallback to 1:1 if API fails
    usdToUsdtRate.value = 1.0
  }
}

async function fetchBybitSwapRate() {
  try {
    const response = await api.get('/api/v1/market/bybit-swap-rate', {
      params: { pair_code: currentPair.value }
    })
    const data = response.data
    // long_swap_per_lot: <0 long pays, >0 long receives
    // short_swap_per_lot: >0 short receives, <0 short pays
    bybitLongSwapFee.value = data.long_swap_per_lot ?? 0
    bybitShortSwapFee.value = data.short_swap_per_lot ?? 0
  } catch (error) {
    console.error('Failed to fetch Bybit swap rate:', error)
  }
}

async function fetchBinanceFundingRate() {
  try {
    const response = await api.get('/api/v1/market/funding-rate', {
      params: { pair_code: currentPair.value }
    })
    const data = response.data
    // long_cost_per_lot: >0 means long pays, <0 means long receives
    // short_cost_per_lot: opposite sign
    binanceLongFundingRate.value = data.long_cost_per_lot ?? 0
    binanceShortFundingRate.value = data.short_cost_per_lot ?? 0
    binanceFundingRatePct.value = data.funding_rate_pct ?? 0
    binanceNextFundingTime.value = data.next_funding_time ?? 0
  } catch (error) {
    console.error('Failed to fetch Binance funding rate:', error)
  }
}

// Export data for StrategyPanel to use
defineExpose({
  reverseActualPosition,
  forwardActualPosition,
  reverseSpread,
  forwardSpread,
  bybitLongSwapFee,
  bybitShortSwapFee,
  binanceLongFundingRate,
  binanceShortFundingRate,
  binanceFundingRatePct,
  binanceNextFundingTime,
  binanceLongTotal,
  binanceShortTotal,
  bybitLongTotal,
  bybitShortTotal
})
</script>

<style scoped>
/* Hide scrollbar but keep scroll functionality */
.scrollbar-hide {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE and Edge */
}

.scrollbar-hide::-webkit-scrollbar {
  display: none; /* Chrome, Safari, Opera */
}

/* Marquee Animation */
.marquee-container {
  overflow: hidden;
  position: relative;
  width: 100%;
}

.marquee-content {
  display: inline-block;
  white-space: nowrap;
  animation: marquee 20s linear infinite;
  will-change: transform;
  -webkit-transform: translateZ(0);
  transform: translateZ(0);
}

.marquee-content:hover {
  animation-play-state: paused;
}

@keyframes marquee {
  0% {
    transform: translateX(100vw);
  }
  100% {
    transform: translateX(-100%);
  }
}

/* Smooth transitions for price updates */
.text-2xl, .text-xl, .text-lg {
  transition: color 0.3s ease-in-out, transform 0.2s ease-in-out;
}

/* Pulse animation for price changes */
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.8;
  }
}

.font-mono {
  transition: all 0.2s ease-in-out;
}

/* Smooth background transitions */
.bg-\[#1e2329\] {
  transition: background-color 0.3s ease-in-out;
}

/* Smooth status indicator transitions */
.bg-green-500, .bg-red-500, .bg-gray-500 {
  transition: background-color 0.3s ease-in-out;
}

/* 移动端H5竖屏适配 - 确保完全撑满宽度 (包括2K屏幕) */
@media (orientation: portrait) and (max-width: 1500px), (max-width: 750px) {
  /* 移除所有内边距，让内容完全撑满 */
  :deep(.grid) {
    width: 100%;
  }

  /* 确保所有子元素也是100%宽度 */
  :deep(.bg-\[\#1e2329\]) {
    width: 100%;
    box-sizing: border-box;
  }

  /* 确保容器占满宽度 */
  .h-full {
    width: 100% !important;
    max-width: 100vw;
  }

  /* 优化内边距 */
  .p-1\.5,
  .p-2 {
    padding: 0.375rem !important;
  }

  /* 统一字体大小 - 适用于所有移动设备（参考iPhone显示效果）*/
  .text-xs {
    font-size: 1rem !important;
  }

  .text-sm {
    font-size: 1.125rem !important;
  }

  .text-base {
    font-size: 1.25rem !important;
  }

  .text-lg {
    font-size: 1.5rem !important;
  }

  /* 统一内边距 */
  .p-1\.5,
  .p-2 {
    padding: 0.65rem !important;
  }

  .p-1 {
    padding: 0.45rem !important;
  }

  /* 统一间距 */
  .gap-1,
  .gap-1\.5,
  .gap-2 {
    gap: 0.45rem !important;
  }

  .space-x-1,
  .space-x-1\.5 {
    margin-left: 0.45rem !important;
  }

  .mb-1,
  .mb-1\.5 {
    margin-bottom: 0.45rem !important;
  }

  /* 统一图标大小 */
  .w-5,
  .h-5 {
    width: 1.5rem !important;
    height: 1.5rem !important;
  }

  .w-4,
  .h-4 {
    width: 1.25rem !important;
    height: 1.25rem !important;
  }

  /* 完全禁用动画 */
  * {
    animation: none !important;
    transition: none !important;
  }
}

/* ========== 移除单独的2K屏幕媒体查询 ========== */


@keyframes liqFlash {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}

.liq-flash {
  animation: liqFlash 0.5s ease-in-out infinite;
}
</style>