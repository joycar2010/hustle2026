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
  // key 格式(2026-07-04 多交易对): '{pair}::{type}_{action}' 或方向级 '{pair}::{type}'。
  // 解析: '::' 前为 pair(隔离维度), 后段沿用原 '_' 解析 dir/action。互斥【仅在同 pair 内】,
  // 跨 pair 完全独立 → 黄金开反向组不再锁住原油/白银的同组按钮。
  function _parseKey(key) {
    const _ci = key.indexOf('::')
    const pair = _ci >= 0 ? key.slice(0, _ci) : ''
    const rest = _ci >= 0 ? key.slice(_ci + 2) : key
    const dir = rest.includes('_') ? rest.split('_')[0] : rest
    const isAction = rest.includes('_')
    return { pair, dir, isAction }
  }

  function acquire(key) {
    if (runningStrategies.value.has(key)) return true

    const k = _parseKey(key)
    for (const running of runningStrategies.value) {
      const r = _parseKey(running)
      if (r.pair !== k.pair) continue  // 跨 pair 独立, 不互斥
      if (r.dir !== k.dir) return false
      if (!r.isAction || !k.isAction) return false
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
    const k = _parseKey(key)
    for (const running of runningStrategies.value) {
      const r = _parseKey(running)
      if (r.pair !== k.pair) continue  // 跨 pair 独立, 不锁
      if (r.dir !== k.dir) return true
      if (!r.isAction || !k.isAction) return true
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
