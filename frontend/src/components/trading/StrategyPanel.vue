<template>
  <div class="h-full flex flex-col max-lg:h-auto">
    <!-- Header -->
    <div class="p-1.5 border-b border-[#2b3139] flex-shrink-0">
      <h3 :class="['text-sm font-bold', type === 'forward' ? 'text-[#FF2433]' : 'text-[#00C98B]']">
        {{ type === 'forward' ? '正向套利策略' : '反向套利策略' }}
      </h3>
      <div v-if="marketCardsRef" class="text-2xl font-bold text-center mt-1 text-[#3b82f6]">
        <span v-if="type === 'reverse'">
          实仓: {{ marketCardsRef.reverseActualPosition?.toFixed(2) || '0.00' }} 点差: {{ marketCardsRef.reverseSpread?.toFixed(2) || '0.00' }}
        </span>
        <span v-else>
          实仓: {{ marketCardsRef.forwardActualPosition?.toFixed(2) || '0.00' }} 点差: {{ marketCardsRef.forwardSpread?.toFixed(2) || '0.00' }}
        </span>
      </div>
    </div>

    <div class="flex-1 p-1.5 space-y-1.5 lg:overflow-y-auto lg:min-h-0 max-lg:overflow-visible max-lg:h-auto">
      <!-- Validation Errors Display -->
      <div v-if="validationErrors.length > 0" class="bg-[#f6465d] bg-opacity-10 border border-[#f6465d] rounded p-2">
        <div class="flex items-start space-x-2">
          <span class="text-[#f6465d] text-base">⚠</span>
          <div class="flex-1">
            <div class="text-xs font-bold text-[#f6465d] mb-0.5">配置验证失败</div>
            <ul class="text-xs text-[#f6465d] space-y-0.5">
              <li v-for="(error, index) in validationErrors" :key="index">• {{ error }}</li>
            </ul>
          </div>
          <button @click="validationErrors = []" class="text-[#f6465d] hover:text-white transition-colors">
            <span class="text-base">×</span>
          </button>
        </div>
      </div>

      <!-- Top Info Bar -->
      <div class="bg-[#252930] rounded p-2 space-y-2">
        <!-- Row 1: Assets (centered) -->
        <div class="flex items-center justify-center gap-4">
          <!-- Binance Available Assets -->
          <div class="text-center">
            <div class="text-xs text-gray-400 mb-0.5">Binance可用资产</div>
            <div class="text-sm font-mono font-bold">
              {{ formatNumber(binanceAssets) }} USDT
            </div>
          </div>

          <!-- Bybit MT5 Available Assets -->
          <div class="text-center">
            <div class="text-xs text-gray-400 mb-0.5">Bybit MT5可用资产</div>
            <div class="text-sm font-mono font-bold">
              {{ formatNumber(bybitAssets) }} USDT
            </div>
          </div>
        </div>

        <!-- Row 2: Spread and Fees (centered) -->
        <div class="flex items-center justify-center gap-4">
          <!-- For Reverse Strategy: Bybit Fee + Spread -->
          <template v-if="type === 'reverse'">
            <!-- Bybit Swap Fee -->
            <div v-if="marketCardsRef" class="text-center">
              <div class="text-xs text-gray-400 mb-0.5">Bybit 掉期费</div>
              <div class="flex gap-2 justify-center">
                <span class="text-[#0ecb81] text-xs font-mono">多: {{ marketCardsRef.bybitLongSwapFee?.toFixed(4) || '0.0000' }}%</span>
                <span class="text-[#f6465d] text-xs font-mono">空: {{ marketCardsRef.bybitShortSwapFee?.toFixed(4) || '0.0000' }}%</span>
              </div>
            </div>

            <!-- Spread -->
            <div class="text-center">
              <div class="text-xs text-gray-400 mb-0.5 whitespace-nowrap">做多Bybit点差</div>
              <div class="text-lg font-mono font-bold whitespace-nowrap text-[#0ecb81]">
                {{ currentSpread.toFixed(2) }} / {{ closingSpread.toFixed(2) }}
              </div>
            </div>
          </template>

          <!-- For Forward Strategy: Spread + Binance Fee -->
          <template v-else>
            <!-- Spread -->
            <div class="text-center">
              <div class="text-xs text-gray-400 mb-0.5 whitespace-nowrap">做多Binance点差</div>
              <div class="text-lg font-mono font-bold whitespace-nowrap text-[#f6465d]">
                {{ currentSpread.toFixed(2) }} / {{ closingSpread.toFixed(2) }}
              </div>
            </div>

            <!-- Binance Funding Rate -->
            <div v-if="marketCardsRef" class="text-center">
              <div class="text-xs text-gray-400 mb-0.5">Binance 资金费</div>
              <div class="flex gap-2 justify-center">
                <span class="text-[#0ecb81] text-xs font-mono">多: {{ marketCardsRef.binanceLongFundingRate?.toFixed(4) || '0.0000' }}%</span>
                <span class="text-[#f6465d] text-xs font-mono">空: {{ marketCardsRef.binanceShortFundingRate?.toFixed(4) || '0.0000' }}%</span>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Configuration Area -->
      <div class="bg-[#252930] rounded p-2 space-y-2">
        <div class="text-xs font-bold mb-1">策略配置</div>

        <!-- M Coin Settings -->
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label :for="`openingMCoin-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正开单手数' : '反开单手数' }} (XAU)
              <span class="text-[#0ecb81] ml-1">≈ {{ xauToLot(config.openingMCoin).toFixed(2) }} Lot</span>
            </label>
            <input
              :id="`openingMCoin-${type}`"
              v-model.number="config.openingMCoin"
              type="number"
              step="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`closingMCoin-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正平单手数' : '反平单手数' }} (XAU)
              <span class="text-[#0ecb81] ml-1">≈ {{ xauToLot(config.closingMCoin).toFixed(2) }} Lot</span>
            </label>
            <input
              :id="`closingMCoin-${type}`"
              v-model.number="config.closingMCoin"
              type="number"
              step="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>
        </div>

        <!-- Opening/Closing Position Toggles -->
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label class="text-xs text-gray-400 mb-0.5 block">开仓控制</label>
            <button
              @click="toggleOpening"
              :disabled="executing"
              :class="[
                'w-full px-2 py-1.5 rounded text-xs font-bold transition-all',
                executing ? 'bg-gray-600 text-gray-400 cursor-not-allowed' :
                config.openingEnabled
                  ? 'bg-[#F1C40F] text-white'
                  : 'bg-[#00C98B] text-white'
              ]"
            >
              {{ executing ? '执行中...' : (config.openingEnabled ? '停用开仓' : (type === 'forward' ? '启用正向开仓' : '启用反向开仓')) }}
            </button>
            <!-- Trigger Progress for Opening -->
            <div v-if="config.openingEnabled" class="mt-1.5 text-xs">
              <div class="flex justify-between text-gray-400 mb-0.5">
                <span>触发进度</span>
                <span>{{ triggerCount.opening }} / {{ config.openingSyncQty }}</span>
              </div>
              <div class="w-full bg-[#1a1d21] rounded-full h-1.5">
                <div
                  class="bg-[#0ecb81] h-1.5 rounded-full transition-all duration-300"
                  :style="{ width: `${Math.min(100, (triggerCount.opening / config.openingSyncQty) * 100)}%` }"
                ></div>
              </div>
            </div>
          </div>

          <div>
            <label class="text-xs text-gray-400 mb-0.5 block">平仓控制</label>
            <button
              @click="toggleClosing"
              :disabled="executing"
              :class="[
                'w-full px-2 py-1.5 rounded text-xs font-bold transition-all',
                executing ? 'bg-gray-600 text-gray-400 cursor-not-allowed' :
                config.closingEnabled
                  ? 'bg-[#F1C40F] text-white'
                  : 'bg-[#f6465d] text-white'
              ]"
            >
              {{ executing ? '执行中...' : (config.closingEnabled ? '停用平仓' : (type === 'forward' ? '启用正向平仓' : '启用反向平仓')) }}
            </button>
            <!-- Trigger Progress for Closing -->
            <div v-if="config.closingEnabled" class="mt-1.5 text-xs">
              <div class="flex justify-between text-gray-400 mb-0.5">
                <span>触发进度</span>
                <span>{{ triggerCount.closing }} / {{ config.closingSyncQty }}</span>
              </div>
              <div class="w-full bg-[#1a1d21] rounded-full h-1.5">
                <div
                  class="bg-[#f6465d] h-1.5 rounded-full transition-all duration-300"
                  :style="{ width: `${Math.min(100, (triggerCount.closing / config.closingSyncQty) * 100)}%` }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Continuous Execution Controls -->
        <div class="border-t border-[#2b3139] pt-2 mt-2">
          <div class="flex items-center justify-between mb-1.5">
            <label class="text-xs text-gray-400">连续执行模式</label>
            <div class="flex gap-2">
              <span v-if="continuousExecutionEnabled.opening" class="text-xs text-[#0ecb81] font-bold">开仓运行中</span>
              <span v-if="continuousExecutionEnabled.closing" class="text-xs text-[#f6465d] font-bold">平仓运行中</span>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2">
            <button
              @click="startContinuousExecution('opening')"
              :disabled="continuousExecutionEnabled.opening || executing"
              :class="[
                'px-2 py-1.5 rounded text-xs font-bold transition-all',
                continuousExecutionEnabled.opening || executing
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-[#0ecb81] text-white hover:bg-[#0db872]'
              ]"
            >
              {{ continuousExecutionEnabled.opening ? '开仓执行中' : '连续开仓' }}
            </button>

            <button
              @click="startContinuousExecution('closing')"
              :disabled="continuousExecutionEnabled.closing || executing"
              :class="[
                'px-2 py-1.5 rounded text-xs font-bold transition-all',
                continuousExecutionEnabled.closing || executing
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-[#f6465d] text-white hover:bg-[#e5394d]'
              ]"
            >
              {{ continuousExecutionEnabled.closing ? '平仓执行中' : '连续平仓' }}
            </button>
          </div>

          <div class="grid grid-cols-2 gap-2 mt-1.5">
            <button
              v-if="continuousExecutionEnabled.opening"
              @click="stopContinuousExecution('opening')"
              class="px-2 py-1 rounded text-xs font-bold bg-[#F1C40F] text-white hover:bg-[#e1b40f] transition-all"
            >
              停止开仓
            </button>
            <button
              v-if="continuousExecutionEnabled.closing"
              @click="stopContinuousExecution('closing')"
              class="px-2 py-1 rounded text-xs font-bold bg-[#F1C40F] text-white hover:bg-[#e1b40f] transition-all"
            >
              停止平仓
            </button>
          </div>

          <!-- Execution Status Display -->
          <div v-if="continuousExecutionStatus.opening || continuousExecutionStatus.closing" class="mt-2 space-y-1.5">
            <div v-if="continuousExecutionStatus.opening" class="p-1.5 bg-[#1a1d21] rounded text-xs">
              <div class="text-[#0ecb81] font-bold mb-0.5">开仓状态</div>
              <div class="flex justify-between mb-0.5">
                <span class="text-gray-400">状态:</span>
                <span :class="[
                  'font-bold',
                  continuousExecutionStatus.opening.status === 'running' ? 'text-[#0ecb81]' :
                  continuousExecutionStatus.opening.status === 'completed' ? 'text-[#00C98B]' :
                  continuousExecutionStatus.opening.status === 'failed' ? 'text-[#f6465d]' :
                  'text-gray-400'
                ]">
                  {{ continuousExecutionStatus.opening.status === 'running' ? '运行中' :
                     continuousExecutionStatus.opening.status === 'completed' ? '已完成' :
                     continuousExecutionStatus.opening.status === 'failed' ? '失败' :
                     continuousExecutionStatus.opening.status }}
                </span>
              </div>
              <div v-if="continuousExecutionStatus.opening.current_ladder !== undefined" class="flex justify-between mb-0.5">
                <span class="text-gray-400">当前阶梯:</span>
                <span class="text-white">{{ continuousExecutionStatus.opening.current_ladder + 1 }}</span>
              </div>
              <div v-if="continuousExecutionStatus.opening.trades_executed !== undefined" class="flex justify-between">
                <span class="text-gray-400">已执行交易:</span>
                <span class="text-white">{{ continuousExecutionStatus.opening.trades_executed }}</span>
              </div>
            </div>

            <div v-if="continuousExecutionStatus.closing" class="p-1.5 bg-[#1a1d21] rounded text-xs">
              <div class="text-[#f6465d] font-bold mb-0.5">平仓状态</div>
              <div class="flex justify-between mb-0.5">
                <span class="text-gray-400">状态:</span>
                <span :class="[
                  'font-bold',
                  continuousExecutionStatus.closing.status === 'running' ? 'text-[#0ecb81]' :
                  continuousExecutionStatus.closing.status === 'completed' ? 'text-[#00C98B]' :
                  continuousExecutionStatus.closing.status === 'failed' ? 'text-[#f6465d]' :
                  'text-gray-400'
                ]">
                  {{ continuousExecutionStatus.closing.status === 'running' ? '运行中' :
                     continuousExecutionStatus.closing.status === 'completed' ? '已完成' :
                     continuousExecutionStatus.closing.status === 'failed' ? '失败' :
                     continuousExecutionStatus.closing.status }}
                </span>
              </div>
              <div v-if="continuousExecutionStatus.closing.current_ladder !== undefined" class="flex justify-between mb-0.5">
                <span class="text-gray-400">当前阶梯:</span>
                <span class="text-white">{{ continuousExecutionStatus.closing.current_ladder + 1 }}</span>
              </div>
              <div v-if="continuousExecutionStatus.closing.trades_executed !== undefined" class="flex justify-between">
                <span class="text-gray-400">已执行交易:</span>
                <span class="text-white">{{ continuousExecutionStatus.closing.trades_executed }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Data Sync Quantities -->
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label :for="`openingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正开次数' : '反开次数' }}
            </label>
            <input
              :id="`openingSyncQty-${type}`"
              v-model.number="config.openingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`closingSyncQty-${type}`" class="text-xs text-gray-400 mb-1 block">
              {{ type === 'forward' ? '正平次数' : '反平次数' }}
            </label>
            <input
              :id="`closingSyncQty-${type}`"
              v-model.number="config.closingSyncQty"
              type="number"
              step="1"
              min="1"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
          </div>

          <div>
            <label :for="`triggerCheckInterval-${type}`" class="text-xs text-gray-400 mb-1 block">
              触发频率
              <span class="text-[#0ecb81] ml-1">{{ config.triggerCheckInterval }}ms</span>
            </label>
            <input
              :id="`triggerCheckInterval-${type}`"
              v-model.number="config.triggerCheckInterval"
              type="number"
              step="10"
              min="10"
              max="1000"
              class="w-full bg-[#1a1d21] border border-[#2b3139] rounded px-2 py-1 text-xs focus:border-[#f0b90b] focus:outline-none"
            />
            <div class="text-xs text-gray-500 mt-0.5">
              建议值: 50ms
            </div>
          </div>
        </div>

        <!-- Save Button -->
        <button
          @click="saveConfig"
          class="w-full px-3 py-1.5 bg-[#f0b90b] text-[#1a1d21] rounded font-bold hover:bg-[#e0a800] transition-colors text-xs"
        >
          保存配置
        </button>
      </div>

      <!-- Ladder Configuration -->
      <div class="bg-[#252930] rounded p-2">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-bold">阶梯配置（最多5级）</span>
          <button
            @click="addLadder"
            :disabled="config.ladders.length >= 5"
            :class="[
              'px-2 py-1 rounded text-xs font-bold transition-colors',
              config.ladders.length >= 5
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-[#f0b90b] text-[#1a1d21] hover:bg-[#e0a800]'
            ]"
          >
            + 添加阶梯
          </button>
        </div>

        <div class="space-y-1.5">
          <div
            v-for="(ladder, index) in config.ladders"
            :key="index"
            class="bg-[#1a1d21] rounded p-1.5"
          >
            <div class="flex items-center justify-between mb-1.5">
              <div class="flex items-center space-x-1.5">
                <span class="text-xs text-gray-400">阶梯 {{ index + 1 }}</span>
                <!-- Phase 3: 失败计数显示 -->
                <span
                  v-if="(ladderFailureCounts.opening[index] || 0) > 0 || (ladderFailureCounts.closing[index] || 0) > 0"
                  class="text-xs px-1.5 py-0.5 rounded bg-[#f6465d] bg-opacity-20 text-[#f6465d]"
                >
                  失败: 开{{ ladderFailureCounts.opening[index] || 0 }}/平{{ ladderFailureCounts.closing[index] || 0 }}
                </span>
              </div>
              <div class="flex items-center space-x-1.5">
                <label :for="`ladder-enabled-${type}-${index}`" class="flex items-center space-x-1 cursor-pointer">
                  <input
                    :id="`ladder-enabled-${type}-${index}`"
                    v-model="ladder.enabled"
                    type="checkbox"
                    class="w-3.5 h-3.5 rounded border-[#2b3139] bg-[#252930] text-[#0ecb81] focus:ring-[#0ecb81]"
                  />
                  <span class="text-xs">启用</span>
                </label>
                <button
                  @click="removeLadder(index)"
                  class="px-1.5 py-0.5 bg-[#f6465d] text-white rounded text-xs hover:bg-[#e03d52] transition-colors"
                >
                  删除
                </button>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-1.5">
              <div>
                <label :for="`openPrice-${type}-${index}`" class="text-xs text-gray-400 mb-0.5 block">
                  {{ type === 'forward' ? '正开差值' : '反开差值' }}
                </label>
                <input
                  :id="`openPrice-${type}-${index}`"
                  v-model.number="ladder.openPrice"
                  type="number"
                  step="0.01"
                  :placeholder="(0).toFixed(2)"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-1.5 py-0.5 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label :for="`threshold-${type}-${index}`" class="text-xs text-gray-400 mb-0.5 block">
                  {{ type === 'forward' ? '正平差值' : '反平差值' }}
                </label>
                <input
                  :id="`threshold-${type}-${index}`"
                  v-model.number="ladder.threshold"
                  type="number"
                  step="0.01"
                  :placeholder="(0).toFixed(2)"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-1.5 py-0.5 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>

              <div>
                <label :for="`qtyLimit-${type}-${index}`" class="text-xs text-gray-400 mb-0.5 block">
                  {{ type === 'forward' ? '正下总手数' : '反下总手数' }} (XAU)
                  <span class="text-[#0ecb81] ml-1">≈ {{ xauToLot(ladder.qtyLimit).toFixed(2) }} Lot</span>
                </label>
                <input
                  :id="`qtyLimit-${type}-${index}`"
                  v-model.number="ladder.qtyLimit"
                  type="number"
                  step="1"
                  class="w-full bg-transparent border border-[#2b3139] rounded px-1.5 py-0.5 text-xs focus:border-[#f0b90b] focus:outline-none"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Save Strategy Button -->
        <button
          @click="saveStrategy"
          class="w-full mt-2 px-3 py-1.5 bg-[#f0b90b] text-[#1a1d21] rounded font-bold hover:bg-[#e0a800] transition-colors text-xs"
        >
          保存策略
        </button>

        <!-- Phase 3: Reset Failure Counts Buttons -->
        <div class="grid grid-cols-2 gap-1.5 mt-1.5">
          <button
            @click="resetLadderFailures('opening')"
            class="px-2 py-1 bg-[#2b3139] text-gray-300 rounded text-xs hover:bg-[#3b4149] transition-colors"
          >
            重置开仓失败计数
          </button>
          <button
            @click="resetLadderFailures('closing')"
            class="px-2 py-1 bg-[#2b3139] text-gray-300 rounded text-xs hover:bg-[#3b4149] transition-colors"
          >
            重置平仓失败计数
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useMarketStore } from '@/stores/market'
import { useNotificationStore } from '@/stores/notification'
import api from '@/services/api'
import { calculateAllSpreads } from '@/composables/useSpreadCalculator'
import { xauToLot } from '@/composables/useQuantityConverter'

const props = defineProps({
  type: {
    type: String,
    required: true,
    validator: (value) => ['forward', 'reverse'].includes(value)
  },
  marketCardsRef: {
    type: Object,
    default: null
  }
})

// LocalStorage keys for persisting strategy enabled states
const STORAGE_KEY_OPENING = `strategy_${props.type}_opening_enabled`
const STORAGE_KEY_CLOSING = `strategy_${props.type}_closing_enabled`
const STORAGE_KEY_LADDER_PROGRESS = `strategy_${props.type}_ladder_progress`

// Helper functions for localStorage
function loadEnabledState(key, defaultValue = false) {
  try {
    const saved = localStorage.getItem(key)
    return saved !== null ? saved === 'true' : defaultValue
  } catch {
    return defaultValue
  }
}

function saveEnabledState(key, value) {
  try {
    localStorage.setItem(key, value.toString())
  } catch (error) {
    console.error('Failed to save enabled state:', error)
  }
}

// 阶梯进度持久化函数
function loadLadderProgress() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_LADDER_PROGRESS)
    if (saved) {
      return JSON.parse(saved)
    }
  } catch (error) {
    console.error('Failed to load ladder progress:', error)
  }
  return {
    opening: { currentLadderIndex: 0, completedQty: 0 },
    closing: { currentLadderIndex: 0, completedQty: 0 }
  }
}

function saveLadderProgress() {
  try {
    localStorage.setItem(STORAGE_KEY_LADDER_PROGRESS, JSON.stringify(ladderProgress.value))
  } catch (error) {
    console.error('Failed to save ladder progress:', error)
  }
}

// Phase 3: 阶梯失败计数管理
function loadLadderFailureCounts() {
  try {
    const saved = localStorage.getItem(`ladder_failures_${configId.value}`)
    if (saved) {
      ladderFailureCounts.value = JSON.parse(saved)
    }
  } catch (error) {
    console.error('Failed to load ladder failure counts:', error)
  }
}

function saveLadderFailureCounts() {
  try {
    localStorage.setItem(
      `ladder_failures_${configId.value}`,
      JSON.stringify(ladderFailureCounts.value)
    )
  } catch (error) {
    console.error('Failed to save ladder failure counts:', error)
  }
}

function resetLadderFailures(type) {
  if (confirm(`确定要重置所有${type === 'opening' ? '开仓' : '平仓'}阶梯的失败计数吗？`)) {
    ladderFailureCounts.value[type] = {}
    saveLadderFailureCounts()
    notificationStore.showStrategyNotification('失败计数已重置', 'success')
  }
}

const marketStore = useMarketStore()
const notificationStore = useNotificationStore()
const currentSpread = ref(0)
const closingSpread = ref(0)
const binanceAssets = ref(10000)
const bybitAssets = ref(8500)
const executingOpening = ref(false)
const executingClosing = ref(false)
const executing = ref(false)
// 全局执行锁：防止多个策略同时执行导致冲突
const executingAnyStrategy = computed(() => executingOpening.value || executingClosing.value)
const accountsData = ref(null)
const orderPlaced = ref({ opening: false, closing: false })
const triggerCount = ref({ opening: 0, closing: 0 })

// Continuous execution state - separate for opening and closing
const continuousExecutionEnabled = ref({ opening: false, closing: false })
const continuousExecutionTaskId = ref({ opening: null, closing: null })
const continuousExecutionStatus = ref({ opening: null, closing: null })
const statusPollingInterval = ref({ opening: null, closing: null })

const config = ref({
  openingMCoin: 5,
  closingMCoin: 5,
  openingEnabled: loadEnabledState(STORAGE_KEY_OPENING, false),
  closingEnabled: loadEnabledState(STORAGE_KEY_CLOSING, false),
  openingSyncQty: 3,
  closingSyncQty: 3,
  triggerCheckInterval: 50, // 触发器检测频率（毫秒）
  ladders: [
    { enabled: true, openPrice: 3.00, threshold: 2.00, qtyLimit: 3 },
    { enabled: true, openPrice: 3.00, threshold: 3.00, qtyLimit: 3 },
    { enabled: false, openPrice: 3.00, threshold: 4.00, qtyLimit: 3 },
  ]
})

const configId = ref(null)
const validationErrors = ref([])

// 阶梯执行进度跟踪
const ladderProgress = ref(loadLadderProgress())

// 阶梯失败计数跟踪（Phase 3）
const MAX_LADDER_FAILURES = 5
const ladderFailureCounts = ref({
  opening: {},  // {0: 3, 1: 0, 2: 5}
  closing: {}
})

onMounted(async () => {
  // Load config from database (including enabled states)
  await loadConfigFromDB()

  // Load ladder failure counts after configId is set
  loadLadderFailureCounts()

  // Ensure WebSocket connection
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Initial account data fetch
  await fetchAccountData()

  // Validate enabled states after all data is loaded
  // If accounts are disconnected, disable strategies and clear localStorage
  if (config.value.openingEnabled || config.value.closingEnabled) {
    const accountValidation = validateAccountsForExecution()
    if (!accountValidation.valid) {
      console.warn('Disabling strategies due to account validation failure:', accountValidation.message)
      if (config.value.openingEnabled) {
        config.value.openingEnabled = false
        saveEnabledState(STORAGE_KEY_OPENING, false)
      }
      if (config.value.closingEnabled) {
        config.value.closingEnabled = false
        saveEnabledState(STORAGE_KEY_CLOSING, false)
      }
      validationErrors.value = [accountValidation.message]
    }
  }
})

async function loadConfigFromDB() {
  try {
    const response = await api.get(`/api/v1/strategies/configs/by-type/${props.type}`)
    const data = response.data
    configId.value = data.config_id
    config.value.openingMCoin = data.opening_m_coin || data.m_coin || 5
    config.value.closingMCoin = data.closing_m_coin || data.m_coin || 5
    config.value.openingSyncQty = data.opening_sync_count
    config.value.closingSyncQty = data.closing_sync_count

    // 保留策略启用状态（如果数据库中有保存）
    if (data.opening_enabled !== undefined) {
      config.value.openingEnabled = data.opening_enabled
    }
    if (data.closing_enabled !== undefined) {
      config.value.closingEnabled = data.closing_enabled
    }

    if (data.ladders && data.ladders.length > 0) {
      config.value.ladders = data.ladders
    }
  } catch (error) {
    if (error.response?.status !== 404) {
      console.error('Failed to load config from DB:', error)
    }
    // 404 means no config yet, use defaults (disabled by default)
    config.value.openingEnabled = false
    config.value.closingEnabled = false
  }
}

onUnmounted(() => {
  // No cleanup needed for WebSocket - stays connected for other components
})

// Watch for market data updates via WebSocket
watch(() => marketStore.marketData, (newData) => {
  if (!newData) return

  // 使用统一的点差计算器
  const spreads = calculateAllSpreads(newData)

  // Update spread based on strategy type
  if (props.type === 'forward') {
    currentSpread.value = spreads.forwardOpening  // 正向开仓点差
    closingSpread.value = spreads.forwardClosing  // 正向平仓点差
  } else {
    currentSpread.value = spreads.reverseOpening  // 反向开仓点差
    closingSpread.value = spreads.reverseClosing  // 反向平仓点差
  }

  // binance做多值: forward=binance_bid, reverse=binance_ask
  const binanceLongValue = props.type === 'forward' ? newData.binance_bid : newData.binance_ask

  // Trigger count logic for opening
  if (config.value.openingEnabled && !executingOpening.value && !orderPlaced.value.opening) {
    const enabledLadders = config.value.ladders.filter(l => l.enabled)
    const currentLadderIdx = ladderProgress.value.opening.currentLadderIndex

    // 只检查当前阶梯（严格顺序执行）
    if (currentLadderIdx < enabledLadders.length) {
      const currentLadder = enabledLadders[currentLadderIdx]

      // 检查是否满足触发条件
      if (currentSpread.value >= currentLadder.openPrice) {
        triggerCount.value.opening++
        console.log(`Opening trigger count: ${triggerCount.value.opening}/${config.value.openingSyncQty}, currentSpread=${currentSpread.value}, openPrice=${currentLadder.openPrice}, ladder=${currentLadderIdx + 1}`)

        if (triggerCount.value.opening >= config.value.openingSyncQty) {
          // 执行当前阶梯
          executeLadderOpening(currentLadderIdx, currentLadder)
          triggerCount.value.opening = 0
        }
      } else {
        triggerCount.value.opening = 0
      }
    }
  }

  // Trigger count logic for closing
  if (config.value.closingEnabled && !executingClosing.value && !orderPlaced.value.closing) {
    const enabledLadders = config.value.ladders.filter(l => l.enabled)
    const currentLadderIdx = ladderProgress.value.closing.currentLadderIndex

    // 只检查当前阶梯（严格顺序执行）
    if (currentLadderIdx < enabledLadders.length) {
      const currentLadder = enabledLadders[currentLadderIdx]

      // 检查是否满足触发条件
      if (closingSpread.value <= currentLadder.threshold) {
        triggerCount.value.closing++
        console.log(`Closing trigger count: ${triggerCount.value.closing}/${config.value.closingSyncQty}, closingSpread=${closingSpread.value}, threshold=${currentLadder.threshold}, ladder=${currentLadderIdx + 1}`)

        if (triggerCount.value.closing >= config.value.closingSyncQty) {
          // 执行当前阶梯
          executeLadderClosing(currentLadderIdx, currentLadder)
          triggerCount.value.closing = 0
        }
      } else {
        triggerCount.value.closing = 0
      }
    }
  }
})

// Watch for account balance updates and strategy status via WebSocket
watch(() => marketStore.lastMessage, (message) => {
  if (!message) return

  if (message.type === 'account_balance') {
    handleAccountBalanceUpdate(message.data)
  } else if (message.type === 'strategy_trigger_progress') {
    handleTriggerProgress(message.data)
  } else if (message.type === 'strategy_position_change') {
    handlePositionChange(message.data)
  } else if (message.type === 'strategy_execution_started') {
    handleExecutionStarted(message.data)
  } else if (message.type === 'strategy_execution_completed') {
    handleExecutionCompleted(message.data)
  } else if (message.type === 'strategy_execution_error') {
    handleExecutionError(message.data)
  } else if (message.type === 'strategy_order_executed') {
    handleOrderExecuted(message.data)
  }
})

// Handle strategy WebSocket events
function handleTriggerProgress(data) {
  // Only handle messages for this strategy
  if (data.strategy_id !== configId.value) return

  // Update trigger count based on action
  if (data.action.includes('opening')) {
    triggerCount.value.opening = data.current_count
  } else if (data.action.includes('closing')) {
    triggerCount.value.closing = data.current_count
  }

  console.log(`[WebSocket] Trigger progress: ${data.current_count}/${data.required_count} for ${data.action}`)
}

function handlePositionChange(data) {
  // Only handle messages for this strategy
  if (data.strategy_id !== configId.value) return

  // Refresh position data
  refreshPositions()

  console.log(`[WebSocket] Position changed: ${data.change_type} ${data.quantity}`)
}

function handleExecutionStarted(data) {
  if (data.strategy_id !== configId.value) return

  executing.value = true
  console.log(`[WebSocket] Execution started: ${data.action}`)
}

function handleExecutionCompleted(data) {
  if (data.strategy_id !== configId.value) return

  executing.value = false
  notificationStore.showStrategyNotification(`策略执行完成: ${data.action}`, 'success')
  console.log(`[WebSocket] Execution completed: ${data.action}`)
}

function handleExecutionError(data) {
  if (data.strategy_id !== configId.value) return

  executing.value = false
  notificationStore.showStrategyNotification(`策略执行错误: ${data.error_message}`, 'error')
  console.log(`[WebSocket] Execution error: ${data.error_message}`)
}

function handleOrderExecuted(data) {
  if (data.strategy_id !== configId.value) return

  // Refresh position data after order execution
  refreshPositions()

  console.log(`[WebSocket] Order executed: Binance ${data.binance_filled}, Bybit ${data.bybit_filled}`)
}

function handleAccountBalanceUpdate(data) {
  // Update available assets from WebSocket data
  if (data.accounts && data.accounts.length > 0) {
    const binanceAccounts = data.accounts.filter(acc => acc.platform_id === 1) || []
    const bybitAccounts = data.accounts.filter(acc => acc.platform_id === 2) || []

    // Use first account's available balance instead of summing all accounts
    binanceAssets.value = binanceAccounts.length > 0 ? (binanceAccounts[0].balance?.available_balance || 0) : 0
    bybitAssets.value = bybitAccounts.length > 0 ? (bybitAccounts[0].balance?.available_balance || 0) : 0
  }
}

async function fetchAccountData() {
  try {
    const accountResponse = await api.get('/api/v1/accounts/dashboard/aggregated')
    const accountData = accountResponse.data

    accountsData.value = accountData

    const binanceAccounts = accountData.accounts?.filter(acc => acc.platform_id === 1) || []
    const bybitAccounts = accountData.accounts?.filter(acc => acc.platform_id === 2) || []

    // Use first account's available balance instead of summing all accounts
    binanceAssets.value = binanceAccounts.length > 0 ? (binanceAccounts[0].balance?.available_balance || 0) : 0
    bybitAssets.value = bybitAccounts.length > 0 ? (bybitAccounts[0].balance?.available_balance || 0) : 0
  } catch (error) {
    console.error('Failed to fetch account data:', error)
  }
}

function addLadder() {
  if (config.value.ladders.length < 5) {
    config.value.ladders.push({
      enabled: true,
      openPrice: 3.00,
      threshold: 0.00,
      qtyLimit: 3
    })
  }
}

function removeLadder(index) {
  config.value.ladders.splice(index, 1)
}

async function saveConfig() {
  try {
    const configData = {
      strategy_type: props.type,
      target_spread: 1.0,
      order_qty: 1.0,
      retry_times: 3,
      mt5_stuck_threshold: 5,
      opening_sync_count: Math.floor(config.value.openingSyncQty),
      closing_sync_count: Math.floor(config.value.closingSyncQty),
      opening_m_coin: Number(config.value.openingMCoin),
      closing_m_coin: Number(config.value.closingMCoin),
      ladders: config.value.ladders.map(l => ({
        enabled: l.enabled,
        openPrice: Number(Number(l.openPrice).toFixed(2)),
        threshold: Number(Number(l.threshold).toFixed(2)),
        qtyLimit: Number(l.qtyLimit)
      })),
      is_enabled: config.value.openingEnabled || config.value.closingEnabled
    }

    const response = await api.post('/api/v1/strategies/configs/upsert', configData)
    configId.value = response.data.config_id
    notificationStore.showStrategyNotification('配置保存成功！', 'success')
  } catch (error) {
    console.error('Failed to save config:', error)
    let errorMessage = '未知错误'
    if (error.response?.data?.detail) {
      if (Array.isArray(error.response.data.detail)) {
        errorMessage = error.response.data.detail.map(err => `${err.loc.join('.')}: ${err.msg}`).join(', ')
      } else if (typeof error.response.data.detail === 'string') {
        errorMessage = error.response.data.detail
      } else {
        errorMessage = JSON.stringify(error.response.data.detail)
      }
    } else if (error.message) {
      errorMessage = error.message
    }
    notificationStore.showStrategyNotification(`配置保存失败: ${errorMessage}`, 'error')
  }
}

async function saveStrategy() {
  await saveConfig()
}

function validateAccountsForExecution() {
  console.log('validateAccountsForExecution called')
  console.log('accountsData.value:', accountsData.value)

  if (!accountsData.value) {
    console.log('Account data not loaded')
    return { valid: false, message: '账户数据未加载，请稍后再试' }
  }

  const accounts = accountsData.value.accounts || []
  console.log('accounts:', accounts)

  // Find Binance and Bybit MT5 accounts
  const binanceAccount = accounts.find(acc => acc.platform_id === 1)
  const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)
  console.log('binanceAccount:', binanceAccount)
  console.log('bybitMT5Account:', bybitMT5Account)

  // Check if accounts exist
  if (!binanceAccount) {
    return { valid: false, message: 'Binance账户不存在，请先添加账户' }
  }

  if (!bybitMT5Account) {
    return { valid: false, message: 'Bybit MT5账户不存在，请先添加账户' }
  }

  // Check disconnected state from localStorage
  const STORAGE_KEY = 'disconnectedAccounts'
  let disconnectedAccounts = new Set()
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      disconnectedAccounts = new Set(JSON.parse(saved))
    }
  } catch (e) {
    console.error('Failed to load disconnected accounts:', e)
  }

  // Check if accounts are disconnected
  if (disconnectedAccounts.has(binanceAccount.account_id)) {
    return { valid: false, message: 'Binance账户已断开连接，请先连接账户' }
  }

  if (disconnectedAccounts.has(bybitMT5Account.account_id)) {
    return { valid: false, message: 'Bybit MT5账户已断开连接，请先连接账户' }
  }

  // Check if both accounts are active
  if (!binanceAccount.is_active) {
    return { valid: false, message: 'Binance账户未激活，请先激活账户' }
  }

  if (!bybitMT5Account.is_active) {
    return { valid: false, message: 'Bybit MT5账户未激活，请先激活账户' }
  }

  // Check if accounts have errors
  if (binanceAccount.error) {
    return { valid: false, message: `Binance账户连接失败: ${binanceAccount.error}` }
  }

  if (bybitMT5Account.error) {
    return { valid: false, message: `Bybit MT5账户连接失败: ${bybitMT5Account.error}` }
  }

  // Check if balances are not zero (use total_assets instead of available_balance)
  const binanceBalance = binanceAccount.balance?.total_assets || binanceAccount.balance?.net_assets || 0
  const bybitBalance = bybitMT5Account.balance?.total_assets || bybitMT5Account.balance?.net_assets || 0

  console.log('Binance balance:', binanceBalance, 'Bybit balance:', bybitBalance)

  if (binanceBalance <= 0) {
    return { valid: false, message: 'Binance合约账户余额为0，无法启用策略' }
  }

  if (bybitBalance <= 0) {
    return { valid: false, message: 'Bybit MT5账户余额为0，无法启用策略' }
  }

  // Check for single-leg mode (if the field exists)
  if (binanceAccount.single_leg_mode) {
    return { valid: false, message: 'Binance账户处于单腿模式，无法启用策略' }
  }

  if (bybitMT5Account.single_leg_mode) {
    return { valid: false, message: 'Bybit MT5账户处于单腿模式，无法启用策略' }
  }

  return { valid: true }
}

async function waitForOrderFill(orderIds, maxWaitTime = 10000) {
  if (!orderIds || orderIds.length === 0) {
    console.log('No order IDs to monitor')
    return
  }

  const startTime = Date.now()
  const pollInterval = 2000 // Poll every 2 seconds

  console.log(`Monitoring orders: ${orderIds.join(', ')}`)

  while (Date.now() - startTime < maxWaitTime) {
    try {
      // Fetch current orders
      const response = await api.get('/api/v1/orders')
      const orders = response.data.orders || []

      // Check if all orders are filled
      const allFilled = orderIds.every(orderId => {
        const order = orders.find(o => o.order_id === orderId)
        if (!order) return false
        return order.status === 'filled'
      })

      if (allFilled) {
        console.log('All orders filled')
        return
      }

      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, pollInterval))
    } catch (error) {
      console.error('Error monitoring orders:', error)
      // Continue polling even if there's an error
      await new Promise(resolve => setTimeout(resolve, pollInterval))
    }
  }

  console.warn('Order monitoring timeout - proceeding anyway')
}

function toggleOpening() {
  if (config.value.openingEnabled) {
    // 禁用策略前检查是否正在执行
    if (executingOpening.value) {
      notificationStore.showStrategyNotification('策略执行中，请稍后再试', 'warning')
      return
    }
    config.value.openingEnabled = false
    triggerCount.value.opening = 0
    validationErrors.value = []
    saveEnabledState(STORAGE_KEY_OPENING, false)
  } else {
    // Clear previous errors
    validationErrors.value = []

    // Validate accounts
    const accountValidation = validateAccountsForExecution()
    if (!accountValidation.valid) {
      validationErrors.value = [accountValidation.message]
      return
    }

    // Validate ladder configuration
    const configValidation = validateLadderConfig('opening')
    if (!configValidation.valid) {
      validationErrors.value = configValidation.errors
      return
    }

    config.value.openingEnabled = true
    orderPlaced.value.opening = false
    triggerCount.value.opening = 0
    saveEnabledState(STORAGE_KEY_OPENING, true)
    // closingEnabled is NOT touched — independent control
  }
}

async function toggleClosing() {
  if (config.value.closingEnabled) {
    // 禁用策略前检查是否正在执行
    if (executingClosing.value) {
      notificationStore.showStrategyNotification('策略执行中，请稍后再试', 'warning')
      return
    }
    config.value.closingEnabled = false
    triggerCount.value.closing = 0
    validationErrors.value = []
    saveEnabledState(STORAGE_KEY_CLOSING, false)
  } else {
    // Clear previous errors
    validationErrors.value = []

    // Validate accounts
    const accountValidation = validateAccountsForExecution()
    if (!accountValidation.valid) {
      validationErrors.value = [accountValidation.message]
      return
    }

    // Validate ladder configuration
    const configValidation = validateLadderConfig('closing')
    if (!configValidation.valid) {
      validationErrors.value = configValidation.errors
      return
    }

    // Check position sufficiency
    const positionCheck = await checkPositionForClosing()
    if (!positionCheck.valid) {
      validationErrors.value = [positionCheck.message]
      return
    }

    config.value.closingEnabled = true
    orderPlaced.value.closing = false
    triggerCount.value.closing = 0
    saveEnabledState(STORAGE_KEY_CLOSING, true)
    // openingEnabled is NOT touched — independent control
  }
}

async function executeLadderOpening(ladderIndex, ladder) {
  // Phase 3: 检查阶梯失败次数，决定是否跳过
  const failureCount = ladderFailureCounts.value.opening[ladderIndex] || 0

  if (failureCount >= MAX_LADDER_FAILURES) {
    console.log(`Skipping ladder ${ladderIndex + 1} due to ${failureCount} consecutive failures`)

    // 跳过到下一个阶梯
    ladderProgress.value.opening.currentLadderIndex++
    ladderProgress.value.opening.completedQty = 0
    saveLadderProgress()

    // 重置失败计数
    ladderFailureCounts.value.opening[ladderIndex] = 0
    saveLadderFailureCounts()

    // 通知用户
    notificationStore.showStrategyNotification(
      `阶梯 ${ladderIndex + 1} 连续失败${failureCount}次，已自动跳过`,
      'warning'
    )

    return
  }

  // 全局互斥锁：防止与其他策略冲突
  if (executingAnyStrategy.value) {
    console.log('Another strategy is executing, skipping opening')
    return
  }

  try {
    executingOpening.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      notificationStore.showStrategyNotification('无法找到账户信息，请刷新页面重试', 'error')
      config.value.openingEnabled = false
      return
    }

    const remainingQty = ladder.qtyLimit - ladderProgress.value.opening.completedQty
    const mCoin = config.value.openingMCoin
    const batchQty = Math.min(mCoin, remainingQty)

    console.log(`Executing ladder ${ladderIndex + 1} opening: batch=${batchQty}, remaining=${remainingQty}, total=${ladder.qtyLimit}`)

    const executionData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      quantity: batchQty,
      ladder_index: ladderIndex,
      target_spread: ladder.threshold
    }

    try {
      const response = await api.post(`/api/v1/strategies/execute/${props.type}`, executionData)

      console.log(`Ladder ${ladderIndex + 1} API response:`, response.data)

      if (response.data.success) {
        console.log(`Ladder ${ladderIndex + 1} batch executed successfully`)
        console.log(`Binance filled: ${response.data.binance_filled_qty}, Bybit filled: ${response.data.bybit_filled_qty}`)

        // Phase 3: 成功执行，重置失败计数
        ladderFailureCounts.value.opening[ladderIndex] = 0
        saveLadderFailureCounts()

        // 检查实际成交数量
        const binanceFilled = response.data.binance_filled_qty || 0
        const bybitFilled = response.data.bybit_filled_qty || 0

        // 如果两边都没有成交，显示警告但保持策略启用（等待下次自动重试）
        if (binanceFilled === 0 && bybitFilled === 0) {
          const message = response.data.message || 'Binance未匹配到订单，等待下次自动重试'
          console.log(`Ladder ${ladderIndex + 1}: ${message}`)
          notificationStore.showStrategyNotification(message, 'warning')
          // 不禁用策略，允许下次触发时自动重试
          return
        }

        // 如果有成交，更新阶梯进度（使用实际成交数量）
        const actualFilled = Math.min(binanceFilled, bybitFilled)
        ladderProgress.value.opening.completedQty += actualFilled
        saveLadderProgress()  // 持久化进度

        // 检查当前阶梯是否完成
        if (ladderProgress.value.opening.completedQty >= ladder.qtyLimit) {
          console.log(`Ladder ${ladderIndex + 1} completed, moving to next ladder`)

          // 移动到下一个阶梯
          ladderProgress.value.opening.currentLadderIndex++
          ladderProgress.value.opening.completedQty = 0
          saveLadderProgress()  // 持久化进度

          // 检查是否所有阶梯都完成
          const enabledLadders = config.value.ladders.filter(l => l.enabled)
          if (ladderProgress.value.opening.currentLadderIndex >= enabledLadders.length) {
            // 所有阶梯完成，停止策略
            console.log('All ladders completed, stopping opening strategy')
            config.value.openingEnabled = false
            ladderProgress.value.opening.currentLadderIndex = 0
            saveLadderProgress()  // 持久化进度
            notificationStore.showStrategyNotification('所有阶梯开仓完成', 'success')
          }
        }

        // Position data will be updated via WebSocket
      } else {
        // Phase 3: 失败时增加失败计数
        const currentFailures = ladderFailureCounts.value.opening[ladderIndex] || 0
        ladderFailureCounts.value.opening[ladderIndex] = currentFailures + 1
        saveLadderFailureCounts()

        const errorMsg = response.data.error || response.data.detail || response.data.message || '未知错误'
        console.error(`Ladder ${ladderIndex + 1} execution failed:`, errorMsg)
        console.log(`Ladder ${ladderIndex + 1} failed ${currentFailures + 1}/${MAX_LADDER_FAILURES} times`)

        notificationStore.showStrategyNotification(`阶梯 ${ladderIndex + 1} 执行失败: ${errorMsg}`, 'error')

        // 如果达到最大失败次数，提示下次将自动跳过
        if (currentFailures + 1 >= MAX_LADDER_FAILURES) {
          notificationStore.showStrategyNotification(
            `阶梯 ${ladderIndex + 1} 已连续失败${currentFailures + 1}次，下次将自动跳过`,
            'error'
          )
        }

        config.value.openingEnabled = false
        saveEnabledState(STORAGE_KEY_OPENING, false)  // Save to localStorage
      }
    } catch (error) {
      // Phase 3: 异常也算失败
      const currentFailures = ladderFailureCounts.value.opening[ladderIndex] || 0
      ladderFailureCounts.value.opening[ladderIndex] = currentFailures + 1
      saveLadderFailureCounts()

      console.error(`Ladder ${ladderIndex + 1} execution error:`, error)
      console.log(`Ladder ${ladderIndex + 1} failed ${currentFailures + 1}/${MAX_LADDER_FAILURES} times`)

      const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
      notificationStore.showStrategyNotification(`阶梯 ${ladderIndex + 1} 执行异常: ${errorMsg}`, 'error')

      config.value.openingEnabled = false
      saveEnabledState(STORAGE_KEY_OPENING, false)  // Save to localStorage
    }
  } finally {
    executingOpening.value = false
  }
}

async function executeLadderClosing(ladderIndex, ladder) {
  // Phase 3: 检查阶梯失败次数，决定是否跳过
  const failureCount = ladderFailureCounts.value.closing[ladderIndex] || 0

  if (failureCount >= MAX_LADDER_FAILURES) {
    console.log(`Skipping ladder ${ladderIndex + 1} closing due to ${failureCount} consecutive failures`)

    // 跳过到下一个阶梯
    ladderProgress.value.closing.currentLadderIndex++
    ladderProgress.value.closing.completedQty = 0
    saveLadderProgress()

    // 重置失败计数
    ladderFailureCounts.value.closing[ladderIndex] = 0
    saveLadderFailureCounts()

    // 通知用户
    notificationStore.showStrategyNotification(
      `阶梯 ${ladderIndex + 1} 平仓连续失败${failureCount}次，已自动跳过`,
      'warning'
    )

    return
  }

  // 全局互斥锁：防止与其他策略冲突
  if (executingAnyStrategy.value) {
    console.log('Another strategy is executing, skipping closing')
    return
  }

  try {
    executingClosing.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      notificationStore.showStrategyNotification('无法找到账户信息，请刷新页面重试', 'error')
      config.value.closingEnabled = false
      return
    }

    const remainingQty = ladder.qtyLimit - ladderProgress.value.closing.completedQty
    const mCoin = config.value.closingMCoin
    const batchQty = Math.min(mCoin, remainingQty)

    console.log(`Executing ladder ${ladderIndex + 1} closing: batch=${batchQty}, remaining=${remainingQty}, total=${ladder.qtyLimit}`)

    const executionData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      quantity: batchQty,
      ladder_index: ladderIndex
    }

    try {
      const response = await api.post(`/api/v1/strategies/close/${props.type}`, executionData)

      if (response.data.success) {
        console.log(`Ladder ${ladderIndex + 1} batch closed successfully`)
        console.log(`Binance filled: ${response.data.binance_filled_qty}, Bybit filled: ${response.data.bybit_filled_qty}`)

        // Phase 3: 成功执行，重置失败计数
        ladderFailureCounts.value.closing[ladderIndex] = 0
        saveLadderFailureCounts()

        // 检查实际成交数量
        const binanceFilled = response.data.binance_filled_qty || 0
        const bybitFilled = response.data.bybit_filled_qty || 0

        // 如果两边都没有成交，显示警告但保持策略启用（等待下次自动重试）
        if (binanceFilled === 0 && bybitFilled === 0) {
          const message = response.data.message || 'Binance未匹配到订单，等待下次自动重试'
          console.log(`Ladder ${ladderIndex + 1}: ${message}`)
          notificationStore.showStrategyNotification(message, 'warning')
          // 不禁用策略，允许下次触发时自动重试
          return
        }

        // 如果有成交，更新阶梯进度（使用实际成交数量）
        const actualFilled = Math.min(binanceFilled, bybitFilled)
        ladderProgress.value.closing.completedQty += actualFilled
        saveLadderProgress()  // 持久化进度

        // 检查当前阶梯是否完成
        if (ladderProgress.value.closing.completedQty >= ladder.qtyLimit) {
          console.log(`Ladder ${ladderIndex + 1} closing completed, moving to next ladder`)

          // 移动到下一个阶梯
          ladderProgress.value.closing.currentLadderIndex++
          ladderProgress.value.closing.completedQty = 0
          saveLadderProgress()  // 持久化进度

          // 检查是否所有阶梯都完成
          const enabledLadders = config.value.ladders.filter(l => l.enabled)
          if (ladderProgress.value.closing.currentLadderIndex >= enabledLadders.length) {
            // 所有阶梯完成，停止策略
            console.log('All ladders closing completed, stopping closing strategy')
            config.value.closingEnabled = false
            ladderProgress.value.closing.currentLadderIndex = 0
            saveLadderProgress()  // 持久化进度
            notificationStore.showStrategyNotification('所有阶梯平仓完成', 'success')
          }
        }

        // Position data will be updated via WebSocket
      } else {
        // Phase 3: 失败时增加失败计数
        const currentFailures = ladderFailureCounts.value.closing[ladderIndex] || 0
        ladderFailureCounts.value.closing[ladderIndex] = currentFailures + 1
        saveLadderFailureCounts()

        const errorMsg = response.data.error || response.data.detail || response.data.message || '未知错误'
        console.error(`Ladder ${ladderIndex + 1} closing failed:`, errorMsg)
        console.log(`Ladder ${ladderIndex + 1} closing failed ${currentFailures + 1}/${MAX_LADDER_FAILURES} times`)

        notificationStore.showStrategyNotification(`阶梯 ${ladderIndex + 1} 平仓失败: ${errorMsg}`, 'error')

        // 如果达到最大失败次数，提示下次将自动跳过
        if (currentFailures + 1 >= MAX_LADDER_FAILURES) {
          notificationStore.showStrategyNotification(
            `阶梯 ${ladderIndex + 1} 平仓已连续失败${currentFailures + 1}次，下次将自动跳过`,
            'error'
          )
        }

        config.value.closingEnabled = false
        saveEnabledState(STORAGE_KEY_CLOSING, false)  // Save to localStorage
      }
    } catch (error) {
      // Phase 3: 异常也算失败
      const currentFailures = ladderFailureCounts.value.closing[ladderIndex] || 0
      ladderFailureCounts.value.closing[ladderIndex] = currentFailures + 1
      saveLadderFailureCounts()

      console.error(`Ladder ${ladderIndex + 1} closing error:`, error)
      console.log(`Ladder ${ladderIndex + 1} closing failed ${currentFailures + 1}/${MAX_LADDER_FAILURES} times`)

      const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
      notificationStore.showStrategyNotification(`阶梯 ${ladderIndex + 1} 平仓异常: ${errorMsg}`, 'error')

      config.value.closingEnabled = false
      saveEnabledState(STORAGE_KEY_CLOSING, false)  // Save to localStorage
    }
  } finally {
    executingClosing.value = false
  }
}

async function executeBatchOpening(ladder) {
  if (executingOpening.value) return

  try {
    executingOpening.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      notificationStore.showStrategyNotification('无法找到账户信息，请刷新页面重试', 'error')
      config.value.openingEnabled = false
      return
    }

    const totalQuantity = ladder.qtyLimit
    const mCoin = config.value.openingMCoin
    const numBatches = Math.ceil(totalQuantity / mCoin)
    let remainingQuantity = totalQuantity

    console.log(`Starting batch opening: total=${totalQuantity}, mCoin=${mCoin}, batches=${numBatches}`)

    for (let i = 0; i < numBatches; i++) {
      const batchQuantity = Math.min(mCoin, remainingQuantity)
      console.log(`Batch ${i + 1}/${numBatches}: executing ${batchQuantity} units`)

      const executionData = {
        binance_account_id: binanceAccount.account_id,
        bybit_account_id: bybitMT5Account.account_id,
        quantity: batchQuantity,
        target_spread: ladder.threshold
      }

      try {
        const response = await api.post(`/api/v1/strategies/execute/${props.type}`, executionData)

        if (response.data.success) {
          console.log(`Batch ${i + 1} executed successfully`)
          remainingQuantity -= batchQuantity

          // Wait for order to be filled before next batch
          if (i < numBatches - 1) {
            await waitForOrderFill(response.data.order_ids)
          }
        } else {
          // Extract error message from various possible fields
          const executionResult = response.data.execution_result || {}
          // binance_result and bybit_result are nested inside execution_result
          const binanceResult = executionResult.binance_result || response.data.binance_result || {}
          const bybitResult = executionResult.bybit_result || response.data.bybit_result || {}

          const errorMsg = response.data.error
            || response.data.detail
            || response.data.message
            || executionResult.error
            || executionResult.message
            || JSON.stringify(executionResult)
            || '未知错误'

          console.error(`Batch ${i + 1} failed:`, errorMsg)
          console.error('Full response:', response.data)
          console.error('Execution result:', executionResult)
          console.error('Binance result:', binanceResult)
          console.error('Bybit result:', bybitResult)

          // Build detailed error message
          let detailedError = errorMsg
          if (binanceResult.error || bybitResult.error) {
            detailedError += '\n详细信息:'
            if (binanceResult.error) detailedError += `\nBinance: ${binanceResult.error}`
            if (bybitResult.error) detailedError += `\nBybit: ${bybitResult.error}`
          }

          notificationStore.showStrategyNotification(`批次 ${i + 1} 执行失败: ${detailedError}`, 'error')
          break
        }
      } catch (error) {
        console.error(`Batch ${i + 1} error:`, error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
        console.error('Full error:', error.response?.data)
        notificationStore.showStrategyNotification(`批次 ${i + 1} 执行异常: ${errorMsg}`, 'error')
        break
      }
    }

    // Mark as completed and disable
    orderPlaced.value.opening = true
    config.value.openingEnabled = false
    console.log('Batch opening completed')
  } catch (error) {
    console.error('Failed to execute batch opening:', error)
  } finally {
    executingOpening.value = false
  }
}

async function executeBatchClosing(ladder) {
  if (executingClosing.value) return

  try {
    executingClosing.value = true

    const accounts = accountsData.value?.accounts || []
    const binanceAccount = accounts.find(acc => acc.platform_id === 1)
    const bybitMT5Account = accounts.find(acc => acc.platform_id === 2 && acc.is_mt5_account)

    if (!binanceAccount || !bybitMT5Account) {
      notificationStore.showStrategyNotification('无法找到账户信息，请刷新页面重试', 'error')
      config.value.closingEnabled = false
      return
    }

    const totalQuantity = ladder.qtyLimit
    const mCoin = config.value.closingMCoin
    const numBatches = Math.ceil(totalQuantity / mCoin)
    let remainingQuantity = totalQuantity

    console.log(`Starting batch closing: total=${totalQuantity}, mCoin=${mCoin}, batches=${numBatches}`)

    for (let i = 0; i < numBatches; i++) {
      const batchQuantity = Math.min(mCoin, remainingQuantity)
      console.log(`Batch ${i + 1}/${numBatches}: executing ${batchQuantity} units`)

      const executionData = {
        binance_account_id: binanceAccount.account_id,
        bybit_account_id: bybitMT5Account.account_id,
        quantity: batchQuantity
      }

      try {
        const response = await api.post(`/api/v1/strategies/close/${props.type}`, executionData)

        if (response.data.success) {
          console.log(`Batch ${i + 1} executed successfully`)
          remainingQuantity -= batchQuantity

          // Wait for order to be filled before next batch
          if (i < numBatches - 1) {
            await waitForOrderFill(response.data.order_ids)
          }
        } else {
          // Extract error message from various possible fields
          const executionResult = response.data.execution_result || {}
          // binance_result and bybit_result are nested inside execution_result
          const binanceResult = executionResult.binance_result || response.data.binance_result || {}
          const bybitResult = executionResult.bybit_result || response.data.bybit_result || {}

          const errorMsg = response.data.error
            || response.data.detail
            || response.data.message
            || executionResult.error
            || executionResult.message
            || JSON.stringify(executionResult)
            || '未知错误'

          console.error(`Batch ${i + 1} failed:`, errorMsg)
          console.error('Full response:', response.data)
          console.error('Execution result:', executionResult)
          console.error('Binance result:', binanceResult)
          console.error('Bybit result:', bybitResult)

          // Build detailed error message
          let detailedError = errorMsg
          if (binanceResult.error || bybitResult.error) {
            detailedError += '\n详细信息:'
            if (binanceResult.error) detailedError += `\nBinance: ${binanceResult.error}`
            if (bybitResult.error) detailedError += `\nBybit: ${bybitResult.error}`
          }

          notificationStore.showStrategyNotification(`批次 ${i + 1} 执行失败: ${detailedError}`, 'error')
          break
        }
      } catch (error) {
        console.error(`Batch ${i + 1} error:`, error)
        const errorMsg = error.response?.data?.detail || error.response?.data?.error || error.message || '未知错误'
        console.error('Full error:', error.response?.data)
        notificationStore.showStrategyNotification(`批次 ${i + 1} 执行异常: ${errorMsg}`, 'error')
        break
      }
    }

    // Mark as completed and disable
    orderPlaced.value.closing = true
    config.value.closingEnabled = false
    console.log('Batch closing completed')
  } catch (error) {
    console.error('Failed to execute batch closing:', error)
  } finally {
    executingClosing.value = false
  }
}

async function checkPositionForClosing() {
  try {
    // Refresh account data to get latest positions
    await fetchAccountData()

    // Get positions from accountsData
    const positions = accountsData.value?.positions || []

    console.log('All positions:', positions)
    console.log('Strategy type:', props.type)

    // Calculate total required quantity from enabled ladders
    const enabledLadders = config.value.ladders.filter(l => l.enabled)
    const totalRequiredQty = enabledLadders.reduce((sum, ladder) => sum + (ladder.qtyLimit || 0), 0)

    // Check positions for BOTH platforms (套利策略需要检查两个平台的持仓)
    // Forward closing: Binance LONG + Bybit SHORT
    // Reverse closing: Binance SHORT + Bybit LONG

    let binancePositions, bybitPositions

    if (props.type === 'forward') {
      // Forward closing: close Binance LONG and Bybit SHORT
      binancePositions = positions.filter(p =>
        p.platform_id === 1 &&
        p.symbol === 'XAUUSDT' &&
        p.side === 'Buy' &&  // LONG position
        p.size > 0
      )

      bybitPositions = positions.filter(p =>
        p.platform_id === 2 &&
        (p.symbol === 'XAUUSD' || p.symbol?.startsWith('XAUUSD')) &&  // Match XAUUSD, XAUUSD.s, etc.
        p.side === 'Sell' &&  // SHORT position
        p.size > 0
      )
    } else {
      // Reverse closing: close Binance SHORT and Bybit LONG
      binancePositions = positions.filter(p =>
        p.platform_id === 1 &&
        p.symbol === 'XAUUSDT' &&
        p.side === 'Sell' &&  // SHORT position
        p.size > 0
      )

      bybitPositions = positions.filter(p =>
        p.platform_id === 2 &&
        (p.symbol === 'XAUUSD' || p.symbol?.startsWith('XAUUSD')) &&  // Match XAUUSD, XAUUSD.s, etc.
        p.side === 'Buy' &&  // LONG position
        p.size > 0
      )
    }

    console.log('Filtered Binance positions:', binancePositions)
    console.log('Filtered Bybit positions:', bybitPositions)

    const binancePosition = binancePositions.reduce((sum, p) => sum + Math.abs(p.size || 0), 0)
    const bybitPosition = bybitPositions.reduce((sum, p) => sum + Math.abs(p.size || 0), 0)

    // Convert Bybit position from Lot to XAU for comparison (1 Lot = 100 XAU)
    const bybitPositionXAU = bybitPosition * 100

    console.log(`Position check for ${props.type} closing:`)
    console.log(`  Binance: ${binancePosition.toFixed(2)} XAU`)
    console.log(`  Bybit: ${bybitPosition.toFixed(2)} Lot (${bybitPositionXAU.toFixed(2)} XAU)`)
    console.log(`  Required: ${totalRequiredQty.toFixed(2)} XAU`)

    // Check if BOTH platforms have sufficient positions
    if (binancePosition < totalRequiredQty) {
      return {
        valid: false,
        message: `Binance持仓不足:\n当前持仓: ${binancePosition.toFixed(2)} XAU\n需要平仓: ${totalRequiredQty.toFixed(2)} XAU\n差额: ${(totalRequiredQty - binancePosition).toFixed(2)} XAU\n\n请调整阶梯配置或等待持仓增加`
      }
    }

    if (bybitPositionXAU < totalRequiredQty) {
      return {
        valid: false,
        message: `Bybit持仓不足:\n当前持仓: ${bybitPosition.toFixed(2)} Lot (${bybitPositionXAU.toFixed(2)} XAU)\n需要平仓: ${(totalRequiredQty / 100).toFixed(2)} Lot (${totalRequiredQty.toFixed(2)} XAU)\n差额: ${((totalRequiredQty - bybitPositionXAU) / 100).toFixed(2)} Lot\n\n请调整阶梯配置或等待持仓增加`
      }
    }

    return { valid: true }
  } catch (error) {
    console.error('Failed to check position:', error)
    return {
      valid: false,
      message: '无法获取持仓信息，请稍后再试'
    }
  }
}

function validateLadderConfig(action) {
  const errors = []

  // Check if there are enabled ladders
  const enabledLadders = config.value.ladders.filter(l => l.enabled)
  if (enabledLadders.length === 0) {
    errors.push('至少需要启用一个阶梯')
    return { valid: false, errors }
  }

  // Check each enabled ladder
  enabledLadders.forEach((ladder) => {
    const ladderNum = config.value.ladders.indexOf(ladder) + 1

    if (action === 'opening') {
      // Check opening spread value
      if (ladder.openPrice === undefined || ladder.openPrice === null) {
        errors.push(`阶梯${ladderNum}: 开差值未配置`)
      }

      // Check opening trigger count (config level)
      if (!config.value.openingSyncQty || config.value.openingSyncQty < 1) {
        errors.push(`开仓触发次数必须至少为1`)
      }

      // Check opening m_coin
      if (!config.value.openingMCoin || config.value.openingMCoin <= 0) {
        errors.push(`开单手数必须大于0`)
      }

      // Check m_coin doesn't exceed total quantity
      if (config.value.openingMCoin > ladder.qtyLimit) {
        errors.push(`阶梯${ladderNum}: 开单手数(${config.value.openingMCoin})不能超过总手数(${ladder.qtyLimit})`)
      }
    } else if (action === 'closing') {
      // Check closing spread value
      if (ladder.threshold === undefined || ladder.threshold === null) {
        errors.push(`阶梯${ladderNum}: 平差值未配置`)
      }

      // Check closing trigger count (config level)
      if (!config.value.closingSyncQty || config.value.closingSyncQty < 1) {
        errors.push(`平仓触发次数必须至少为1`)
      }

      // Check closing m_coin
      if (!config.value.closingMCoin || config.value.closingMCoin <= 0) {
        errors.push(`平单手数必须大于0`)
      }

      // Check m_coin doesn't exceed total quantity
      if (config.value.closingMCoin > ladder.qtyLimit) {
        errors.push(`阶梯${ladderNum}: 平单手数(${config.value.closingMCoin})不能超过总手数(${ladder.qtyLimit})`)
      }
    }

    // Check total quantity
    if (!ladder.qtyLimit || ladder.qtyLimit <= 0) {
      errors.push(`阶梯${ladderNum}: 总手数必须大于0`)
    }
  })

  return {
    valid: errors.length === 0,
    errors
  }
}

function formatNumber(num) {
  return num.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

// Continuous execution methods
async function startContinuousExecution(action) {
  try {
    // Validate configuration
    const validation = validateLadderConfig(action)
    if (!validation.valid) {
      validationErrors.value = validation.errors
      return
    }

    // Validate accounts
    const accountValidation = validateAccountsForExecution()
    if (!accountValidation.valid) {
      notificationStore.showStrategyNotification(accountValidation.message, 'error')
      return
    }

    const binanceAccount = accountsData.value.accounts.find(a => a.platform_id === 1)
    const bybitMT5Account = accountsData.value.accounts.find(a => a.platform_id === 2)

    // Prepare ladder configurations
    const ladders = config.value.ladders
      .filter(l => l.enabled)
      .map(ladder => ({
        enabled: true,
        opening_spread: ladder.openPrice || 0,
        closing_spread: ladder.threshold || 0,
        total_qty: ladder.qtyLimit || 0,
        opening_trigger_count: config.value.openingSyncQty || 1,
        closing_trigger_count: config.value.closingSyncQty || 1
      }))

    const requestData = {
      binance_account_id: binanceAccount.account_id,
      bybit_account_id: bybitMT5Account.account_id,
      opening_m_coin: config.value.openingMCoin || 5,
      closing_m_coin: config.value.closingMCoin || 5,
      ladders: ladders,
      trigger_check_interval: (config.value.triggerCheckInterval || 50) / 1000 // Convert ms to seconds
    }

    // Determine endpoint based on action and strategy type
    let endpoint = ''
    if (action === 'opening') {
      endpoint = `/api/v1/strategies/execute/${props.type}/continuous`
    } else {
      endpoint = `/api/v1/strategies/close/${props.type}/continuous`
    }

    console.log('Sending continuous execution request:', { endpoint, requestData })
    const response = await api.post(endpoint, requestData)
    console.log('Continuous execution response:', response.data)

    if (response.data.task_id) {
      continuousExecutionTaskId.value[action] = response.data.task_id
      continuousExecutionEnabled.value[action] = true

      console.log('Task ID received:', response.data.task_id)

      // Start polling for status
      startStatusPolling(action)

      notificationStore.showStrategyNotification(`连续${action === 'opening' ? '开仓' : '平仓'}已启动`, 'success')
    } else {
      console.error('No task_id in response:', response.data)
      notificationStore.showStrategyNotification('启动失败：未收到任务ID', 'error')
    }
  } catch (error) {
    console.error('Failed to start continuous execution:', error)
    const errorMsg = error.response?.data?.detail || error.message || '未知错误'
    notificationStore.showStrategyNotification(`启动连续执行失败: ${errorMsg}`, 'error')
  }
}

async function stopContinuousExecution(action) {
  try {
    if (!continuousExecutionTaskId.value[action]) {
      return
    }

    await api.post(`/api/v1/strategies/execution/${continuousExecutionTaskId.value[action]}/stop`)

    continuousExecutionEnabled.value[action] = false
    continuousExecutionStatus.value[action] = null  // Clear status to hide the status display
    stopStatusPolling(action)

    notificationStore.showStrategyNotification(`连续${action === 'opening' ? '开仓' : '平仓'}已停止`, 'info')
  } catch (error) {
    console.error('Failed to stop continuous execution:', error)
    const errorMsg = error.response?.data?.detail || error.message || '未知错误'
    notificationStore.showStrategyNotification(`停止连续执行失败: ${errorMsg}`, 'error')
  }
}

function startStatusPolling(action) {
  if (statusPollingInterval.value[action]) {
    clearInterval(statusPollingInterval.value[action])
  }

  statusPollingInterval.value[action] = setInterval(async () => {
    await fetchExecutionStatus(action)
  }, 1000) // Poll every second
}

function stopStatusPolling(action) {
  if (statusPollingInterval.value[action]) {
    clearInterval(statusPollingInterval.value[action])
    statusPollingInterval.value[action] = null
  }
}

async function fetchExecutionStatus(action) {
  try {
    if (!continuousExecutionTaskId.value[action]) {
      return
    }

    const response = await api.get(`/api/v1/strategies/execution/${continuousExecutionTaskId.value[action]}/status`)
    // 后端返回格式: { success: true, task: {...} }
    const taskStatus = response.data.task || response.data
    continuousExecutionStatus.value[action] = taskStatus

    // If task completed or failed, stop polling
    if (taskStatus.status === 'completed' || taskStatus.status === 'failed' || taskStatus.status === 'cancelled') {
      continuousExecutionEnabled.value[action] = false
      stopStatusPolling(action)

      if (taskStatus.status === 'completed') {
        notificationStore.showStrategyNotification(`连续${action === 'opening' ? '开仓' : '平仓'}已完成`, 'success')
      } else if (taskStatus.status === 'failed') {
        notificationStore.showStrategyNotification(`连续${action === 'opening' ? '开仓' : '平仓'}失败`, 'error')
      }
    }
  } catch (error) {
    console.error('Failed to fetch execution status:', error)
  }
}

// Cleanup on component unmount
onUnmounted(() => {
  stopStatusPolling('opening')
  stopStatusPolling('closing')
})
</script>
