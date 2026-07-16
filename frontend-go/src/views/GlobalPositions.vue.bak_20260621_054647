<template>
  <div class="px-4 py-4 md:px-6 md:py-6 max-w-7xl mx-auto">

    <!-- 标题栏 -->
    <div class="flex items-center justify-between mb-5">
      <div class="flex items-center gap-3">
        <h1 class="text-2xl font-bold">全局持仓</h1>
        <span class="px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary border border-primary/20">实时</span>
      </div>
      <span class="text-xs" :class="connected ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
        {{ connected ? '🟢 WebSocket已连接' : '🔴 WebSocket断开' }}
      </span>
    </div>

    <!-- 无持仓提示 -->
    <div v-if="!hasPairs" class="text-center py-16 bg-[#1e2329] rounded-2xl border border-[#2b3139]">
      <div class="text-4xl mb-3">📊</div>
      <div class="text-text-tertiary text-lg">当前无持仓数据</div>
      <div class="text-xs text-text-tertiary mt-2">等待 WebSocket 实时推送...</div>
    </div>

    <!-- 产品对持仓卡片列表 -->
    <div v-else class="space-y-5">
      <div v-for="card in pairCards" :key="card.pairCode"
        class="bg-[#1e2329] rounded-2xl border border-[#2b3139] p-5">

        <!-- 卡片标题 -->
        <div class="flex items-center gap-3 mb-4">
          <div class="w-1.5 h-6 rounded-full" :class="card.hasPosition ? 'bg-primary' : 'bg-[#2b3139]'"></div>
          <h2 class="text-base font-bold">{{ card.pairCode }}</h2>
          <span class="text-xs text-gray-400">{{ card.symA }} / {{ card.symB }}</span>
          <span v-if="!card.hasPosition" class="text-xs text-text-tertiary italic">（空仓）</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

          <!-- ── 套利策略持仓 ────────────────────────────────────────────── -->
          <div class="space-y-3">

            <!-- 反向套利：对冲多仓 + 主空仓 -->
            <div class="bg-[#252930] rounded-xl p-3 border border-[#2b3139]">
              <div class="text-[10px] text-[#f6465d] font-semibold mb-2 uppercase tracking-wide">↕ 反向套利持仓</div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <div class="text-[10px] text-text-tertiary">对冲多仓（MT5 Long）</div>
                  <div class="text-lg font-mono font-bold mt-0.5"
                    :class="card.mt5Long > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary'">
                    {{ card.mt5Long > 0 ? '+' + (card.mt5Long * 100).toFixed(0) : '--' }}
                    <span v-if="card.mt5Long > 0" class="text-xs font-normal text-text-tertiary">oz</span>
                  </div>
                  <div v-if="card.mt5Long > 0" class="text-[10px] text-text-tertiary">{{ card.mt5Long.toFixed(4) }} 手</div>
                </div>
                <div>
                  <div class="text-[10px] text-text-tertiary">主空仓（Binance Short）</div>
                  <div class="text-lg font-mono font-bold mt-0.5"
                    :class="card.binanceShort > 0 ? 'text-[#f6465d]' : 'text-text-tertiary'">
                    {{ card.binanceShort > 0 ? '-' + card.binanceShort.toFixed(2) : '--' }}
                    <span v-if="card.binanceShort > 0" class="text-xs font-normal text-text-tertiary">张</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 正向套利：主多仓 + 对冲空仓 -->
            <div class="bg-[#252930] rounded-xl p-3 border border-[#2b3139]">
              <div class="text-[10px] text-[#0ecb81] font-semibold mb-2 uppercase tracking-wide">↕ 正向套利持仓</div>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <div class="text-[10px] text-text-tertiary">主多仓（Binance Long）</div>
                  <div class="text-lg font-mono font-bold mt-0.5"
                    :class="card.binanceLong > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary'">
                    {{ card.binanceLong > 0 ? '+' + card.binanceLong.toFixed(2) : '--' }}
                    <span v-if="card.binanceLong > 0" class="text-xs font-normal text-text-tertiary">张</span>
                  </div>
                </div>
                <div>
                  <div class="text-[10px] text-text-tertiary">对冲空仓（MT5 Short）</div>
                  <div class="text-lg font-mono font-bold mt-0.5"
                    :class="card.mt5Short > 0 ? 'text-[#f6465d]' : 'text-text-tertiary'">
                    {{ card.mt5Short > 0 ? '-' + (card.mt5Short * 100).toFixed(0) : '--' }}
                    <span v-if="card.mt5Short > 0" class="text-xs font-normal text-text-tertiary">oz</span>
                  </div>
                  <div v-if="card.mt5Short > 0" class="text-[10px] text-text-tertiary">{{ card.mt5Short.toFixed(4) }} 手</div>
                </div>
              </div>
            </div>

            <!-- 费率 -->
            <div class="bg-[#252930] rounded-xl p-3 border border-[#2b3139]">
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <div class="text-[10px] text-text-tertiary mb-1">对冲过夜费</div>
                  <div class="flex gap-3 text-xs font-mono">
                    <span :class="card.swapLong <= 0 ? 'text-[#f6465d]' : 'text-[#0ecb81]'">
                      多:{{ card.swapLong >= 0 ? '+' : '' }}{{ card.swapLong.toFixed(2) }}
                    </span>
                    <span :class="card.swapShort >= 0 ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                      空:{{ card.swapShort >= 0 ? '+' : '' }}{{ card.swapShort.toFixed(2) }}
                    </span>
                  </div>
                </div>
                <div>
                  <div class="text-[10px] text-text-tertiary mb-1">主账号资金费/手</div>
                  <div class="text-xs font-mono text-text-primary">
                    {{ fundingRatePct.toFixed(4) }}%
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ── 行情价格 & 强平价 ──────────────────────────────────────── -->
          <div class="space-y-3">
            <!-- 对冲账户 MT5 -->
            <div class="bg-[#0d1117] rounded-xl p-3 border border-[#2b3139]">
              <div class="flex items-center justify-between mb-2">
                <div class="text-[10px] text-purple-400 font-semibold">对冲账户 (MT5) · {{ card.symB }}</div>
                <span class="text-xs font-mono text-white">{{ fmtPrice(card.bybitMid) }}</span>
              </div>
              <div class="flex items-center justify-between">
                <!-- 多强平 -->
                <div class="text-center">
                  <div class="text-[9px] text-[#0ecb81]">▲ 多强平</div>
                  <div class="text-sm font-mono font-bold"
                    :class="card.mt5LiqLong > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary'">
                    {{ card.mt5LiqLong > 0 ? card.mt5LiqLong.toFixed(2) : 'N/A' }}
                  </div>
                  <div v-if="card.mt5LiqLong > 0 && card.bybitMid > 0"
                    class="text-[9px] mt-0.5"
                    :class="Math.abs(card.bybitMid - card.mt5LiqLong) < 50 ? 'text-[#f0b90b]' : 'text-text-tertiary'">
                    距{{ (card.bybitMid - card.mt5LiqLong).toFixed(1) }}
                  </div>
                </div>
                <!-- 实时价格 -->
                <div class="text-center px-2">
                  <div class="text-xl font-mono font-bold text-white">{{ fmtPrice(card.bybitMid) }}</div>
                  <div class="text-[9px] text-text-tertiary">USDT</div>
                </div>
                <!-- 空强平 -->
                <div class="text-center">
                  <div class="text-[9px] text-[#f6465d]">▼ 空强平</div>
                  <div class="text-sm font-mono font-bold"
                    :class="card.mt5LiqShort > 0 ? 'text-[#f6465d]' : 'text-text-tertiary'">
                    {{ card.mt5LiqShort > 0 ? card.mt5LiqShort.toFixed(2) : 'N/A' }}
                  </div>
                  <div v-if="card.mt5LiqShort > 0 && card.bybitMid > 0"
                    class="text-[9px] mt-0.5"
                    :class="Math.abs(card.mt5LiqShort - card.bybitMid) < 50 ? 'text-[#f0b90b]' : 'text-text-tertiary'">
                    距{{ (card.mt5LiqShort - card.bybitMid).toFixed(1) }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 主账户 Binance -->
            <div class="bg-[#0d1117] rounded-xl p-3 border border-[#2b3139]">
              <div class="flex items-center justify-between mb-2">
                <div class="text-[10px] text-[#f0b90b] font-semibold">主账户 (Binance) · {{ card.symA }}</div>
                <span class="text-xs font-mono text-white">{{ fmtPrice(card.binanceMid) }}</span>
              </div>
              <div class="flex items-center justify-between">
                <div class="text-center">
                  <div class="text-[9px] text-[#0ecb81]">▲ 多强平</div>
                  <div class="text-sm font-mono font-bold"
                    :class="card.binanceLiqLong > 0 ? 'text-[#0ecb81]' : 'text-text-tertiary'">
                    {{ card.binanceLiqLong > 0 ? card.binanceLiqLong.toFixed(2) : 'N/A' }}
                  </div>
                </div>
                <div class="text-center px-2">
                  <div class="text-xl font-mono font-bold text-white">{{ fmtPrice(card.binanceMid) }}</div>
                  <div class="text-[9px] text-text-tertiary">USDT</div>
                </div>
                <div class="text-center">
                  <div class="text-[9px] text-[#f6465d]">▼ 空强平</div>
                  <div class="text-sm font-mono font-bold"
                    :class="card.binanceLiqShort > 0 ? 'text-[#f6465d]' : 'text-text-tertiary'">
                    {{ card.binanceLiqShort > 0 ? card.binanceLiqShort.toFixed(2) : 'N/A' }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useMarketStore } from '@/stores/market'
import { useStrategyStore } from '@/stores/strategy'
import { TRADING_PAIRS } from '@/composables/useTradingPair'
import api from '@/services/api'

const marketStore   = useMarketStore()
const strategyStore = useStrategyStore()

const connected = computed(() => marketStore.connected)

// ── 全产品对持仓（来自 position_snapshot.pairs）────────────────────────────
const pairsData = computed(() => marketStore.positionSnapshot.pairs ?? {})

// ── 实时价格（来自 marketStore.marketData，当前选中产品对）──────────────────
// Note: marketData 仅含当前选中产品对价格；其他对需要独立读取
// 这里使用当前 marketData 作为 XAU/BXAU 价格，其他产品对暂用同价格
const md = computed(() => marketStore.marketData)
const bybitMid   = computed(() => md.value.bybit_mid   ?? 0)
const binanceMid = computed(() => md.value.binance_mid ?? 0)

// ── 强平价（仅支持当前 XAU 产品对）──────────────────────────────────────────
const liq = computed(() => strategyStore.liquidationPrices)

// ── 过夜费 / 资金费（轮询）───────────────────────────────────────────────────
const swapRates = ref({})     // { pair_code: { long, short } }
const fundingRatePct = ref(0)
let feeTimer = null

async function fetchFees() {
  for (const pair of TRADING_PAIRS) {
    try {
      const [swapRes, fundRes] = await Promise.all([
        api.get('/api/v1/market/bybit-swap-rate',   { params: { pair_code: pair.code } }),
        api.get('/api/v1/market/funding-rate',       { params: { pair_code: pair.code } }),
      ])
      swapRates.value[pair.code] = {
        long:  swapRes.data?.long_swap_per_lot  ?? 0,
        short: swapRes.data?.short_swap_per_lot ?? 0,
      }
      if (pair.code === 'XAU') {
        fundingRatePct.value = fundRes.data?.funding_rate_pct ?? 0
      }
    } catch (e) { /* silent */ }
  }
}

// ── 构建卡片数据 ──────────────────────────────────────────────────────────────
const pairCards = computed(() => {
  return TRADING_PAIRS.map(pair => {
    const pd = pairsData.value[pair.pairCode || pair.code] ?? {}
    const mt5Long      = pd.mt5_long      ?? 0
    const mt5Short     = pd.mt5_short     ?? 0
    const binanceLong  = pd.binance_long  ?? 0
    const binanceShort = pd.binance_short ?? 0

    const hasPosition = mt5Long > 0 || mt5Short > 0 || binanceLong > 0 || binanceShort > 0

    const swap = swapRates.value[pair.code] ?? { long: 0, short: 0 }

    // 强平价：仅 XAU/BXAU 可从 strategyStore 获取（其他对暂无）
    const isXAU = pair.code === 'XAU' || pair.code === 'BXAU'
    const mt5LiqLong      = isXAU ? (liq.value.mt5?.long     ?? 0) : 0
    const mt5LiqShort     = isXAU ? (liq.value.mt5?.short    ?? 0) : 0
    const binanceLiqLong  = isXAU ? (liq.value.binance?.long  ?? 0) : 0
    const binanceLiqShort = isXAU ? (liq.value.binance?.short ?? 0) : 0

    return {
      pairCode:      pair.code,
      symA:          pair.binance,
      symB:          pair.mt5,
      mt5Long, mt5Short, binanceLong, binanceShort,
      hasPosition,
      swapLong:      swap.long,
      swapShort:     swap.short,
      bybitMid:      bybitMid.value,
      binanceMid:    binanceMid.value,
      mt5LiqLong, mt5LiqShort, binanceLiqLong, binanceLiqShort,
    }
  })
})

// 只显示有持仓的卡片，或全部（按需）— 这里显示所有，有仓位的排前面
const hasPairs = computed(() => Object.keys(pairsData.value).length > 0)

function fmtPrice(v) {
  if (!v || v === 0) return '--'
  return v.toFixed(2)
}

onMounted(() => {
  fetchFees()
  feeTimer = setInterval(fetchFees, 300000) // fees change infrequently; poll every 5 min
})
onUnmounted(() => clearInterval(feeTimer))
</script>
