/**
 * Strategy Execution Lock Store
 *
 * 全局策略互斥锁。同一时刻最多只允许一个策略运行：
 *   正向开仓 / 正向平仓 / 反向开仓 / 反向平仓
 *
 * key 格式: '{type}_{action}'  → 'forward_opening' | 'forward_closing' | 'reverse_opening' | 'reverse_closing'
 *
 * 同时存储强平价（liquidation prices），供 MarketCards 在行情卡片中展示。
 * 数据由 AccountStatusPanel 在收到 account_balance WS 消息时写入，
 * MarketCards 订阅读取，无需父子通信或额外 API 请求。
 *
 * 设计原则（量化工程）：
 * - 单一真相源：所有 StrategyPanel 实例共享同一个 activeStrategy 状态
 * - 原子操作：acquire/release 保证不会出现竞态
 * - 容错：策略完成/失败时自动释放锁（防止锁永久持有）
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useStrategyStore = defineStore('strategy', () => {
  // ── 策略互斥锁 ────────────────────────────────────────────────────────────
  // 当前运行中的策略 key，null 表示空闲
  const activeStrategy = ref(null)

  // 是否有任何策略正在运行
  const isAnyRunning = computed(() => activeStrategy.value !== null)

  /**
   * 尝试获取策略锁
   * @param {string} key  e.g. 'forward_opening'
   * @returns {boolean}  true=获取成功，false=已有其他策略在运行
   */
  function acquire(key) {
    if (activeStrategy.value !== null && activeStrategy.value !== key) {
      return false  // 被其他策略占用
    }
    activeStrategy.value = key
    return true
  }

  /**
   * 释放策略锁
   * @param {string} key  只有持有该 key 的调用者才能释放
   */
  function release(key) {
    if (activeStrategy.value === key) {
      activeStrategy.value = null
    }
  }

  /**
   * 检查指定 key 是否是当前运行中的策略
   */
  function isActive(key) {
    return activeStrategy.value === key
  }

  /**
   * 检查按钮是否应该被禁用
   * - 如果没有策略在运行 → 全部可用
   * - 如果某策略在运行 → 只有该策略的"停止"按钮可用，其余全部禁用
   */
  function isLocked(key) {
    return activeStrategy.value !== null && activeStrategy.value !== key
  }

  // ── 强平价（Liquidation Prices）────────────────────────────────────────────
  // 由 AccountStatusPanel 在 account_balance WS 更新时写入
  // 按产品对(pair_code)隔离的强平价
  // 结构: { XAU: { binance: {long, short}, mt5: {long, short} }, BZ: {...} }
  const liquidationPrices = ref({})

  function _ensurePair(pairCode) {
    if (!liquidationPrices.value[pairCode]) {
      liquidationPrices.value[pairCode] = {
        binance: { long: null, short: null },
        mt5:     { long: null, short: null },
      }
    }
  }

  /**
   * 更新指定产品对的强平价
   * @param {string} pairCode - 产品对代码 (如 'XAU', 'BZ')
   * @param {'binance'|'mt5'} platform
   * @param {number|null} longPrice
   * @param {number|null} shortPrice
   */
  function setLiquidationPrices(pairCode, platform, longPrice, shortPrice) {
    _ensurePair(pairCode)
    liquidationPrices.value[pairCode][platform] = {
      long:  longPrice  > 0 ? longPrice  : null,
      short: shortPrice > 0 ? shortPrice : null,
    }
    // Force reactivity trigger by replacing the top-level object
    liquidationPrices.value = { ...liquidationPrices.value }
  }

  /**
   * 获取指定产品对的强平价
   * @param {string} pairCode
   * @returns {{ binance: {long, short}, mt5: {long, short} }}
   */
  function getLiquidationPrices(pairCode) {
    return liquidationPrices.value[pairCode] || {
      binance: { long: null, short: null },
      mt5:     { long: null, short: null },
    }
  }

  return {
    // 策略锁
    activeStrategy, isAnyRunning, acquire, release, isActive, isLocked,
    // 强平价 (按产品对隔离)
    liquidationPrices, setLiquidationPrices, getLiquidationPrices,
  }
})

