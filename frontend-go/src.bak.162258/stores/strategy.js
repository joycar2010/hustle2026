/**
 * Strategy Execution Lock Store — 并发开平仓模式
 *
 * 同方向开仓+平仓可同时运行（Set 集合锁），跨方向互斥。
 *
 * key 格式: '{type}_{action}'  → 'forward_opening' | 'forward_closing' | 'reverse_opening' | 'reverse_closing'
 *
 * 互斥矩阵:
 *   forward_opening + forward_closing  → 共存 ✅
 *   forward_opening + reverse_opening  → 互斥 ❌
 *   forward_opening + forward_opening  → 幂等 ✅
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useStrategyStore = defineStore('strategy', () => {
  // ── 并发策略锁（Set 模式）──────────────────────────────────────────────
  const runningStrategies = ref(new Set())

  const isAnyRunning = computed(() => runningStrategies.value.size > 0)

  // 向后兼容：返回 Set 中第一个 key（用于错误提示消息）
  const activeStrategy = computed(() => {
    const arr = [...runningStrategies.value]
    return arr.length > 0 ? arr[0] : null
  })

  /**
   * 尝试获取策略锁
   * 同方向动作级锁可共存，跨方向互斥
   */
  function acquire(key) {
    if (runningStrategies.value.has(key)) return true

    const keyDir = key.includes('_') ? key.split('_')[0] : key
    const keyIsAction = key.includes('_')

    for (const running of runningStrategies.value) {
      const runDir = running.includes('_') ? running.split('_')[0] : running
      const runIsAction = running.includes('_')

      if (runDir !== keyDir) return false
      if (!runIsAction || !keyIsAction) return false
    }

    runningStrategies.value = new Set([...runningStrategies.value, key])
    return true
  }

  /**
   * 释放策略锁
   */
  function release(key) {
    if (runningStrategies.value.has(key)) {
      const next = new Set(runningStrategies.value)
      next.delete(key)
      runningStrategies.value = next
    }
  }

  function isActive(key) {
    return runningStrategies.value.has(key)
  }

  /**
   * 检查按钮是否应该被禁用
   * - 无策略运行 → 全部可用
   * - 当前 key 已在运行 → 不锁（显示停止按钮）
   * - 同方向其他动作在运行 → 不锁（允许并发）
   * - 跨方向策略在运行 → 锁定
   */
  function isLocked(key) {
    if (runningStrategies.value.size === 0) return false
    if (runningStrategies.value.has(key)) return false
    const keyDir = key.includes('_') ? key.split('_')[0] : key
    const keyIsAction = key.includes('_')
    for (const running of runningStrategies.value) {
      const runDir = running.includes('_') ? running.split('_')[0] : running
      const runIsAction = running.includes('_')
      if (runDir !== keyDir) return true
      if (!runIsAction || !keyIsAction) return true
    }
    return false
  }

  // ── 强平价（Liquidation Prices）────────────────────────────────────────────
  const liquidationPrices = ref({})

  function _ensurePair(pairCode) {
    if (!liquidationPrices.value[pairCode]) {
      liquidationPrices.value[pairCode] = {
        binance: { long: null, short: null },
        mt5:     { long: null, short: null },
      }
    }
  }

  function setLiquidationPrices(pairCode, platform, longPrice, shortPrice) {
    _ensurePair(pairCode)
    liquidationPrices.value[pairCode][platform] = {
      long:  longPrice  > 0 ? longPrice  : null,
      short: shortPrice > 0 ? shortPrice : null,
    }
    liquidationPrices.value = { ...liquidationPrices.value }
  }

  function getLiquidationPrices(pairCode) {
    return liquidationPrices.value[pairCode] || {
      binance: { long: null, short: null },
      mt5:     { long: null, short: null },
    }
  }

  return {
    // 策略锁
    activeStrategy, runningStrategies, isAnyRunning, acquire, release, isActive, isLocked,
    // 强平价
    liquidationPrices, setLiquidationPrices, getLiquidationPrices,
  }
})
