/**
 * 统一的数量单位转换管理组件
 *
 * 单位定义：
 * - Binance: XAU (盎司) - 1 XAU = 1 合约单位
 * - Bybit MT5: Lot (手) - 1 Lot = 100 XAU
 *
 * 转换公式：
 * - Bybit Lot = Binance XAU ÷ 100
 * - Binance XAU = Bybit Lot × 100
 */

// 转换常量
export const QUANTITY_CONVERSION = {
  XAU_PER_LOT: 100,           // 1 Lot = 100 XAU
  LOT_PRECISION: 2,           // Lot精度：2位小数
  XAU_PRECISION: 0,           // XAU精度：整数
  MIN_LOT: 0.01,              // Bybit最小下单量：0.01 Lot
  MIN_XAU: 1,                 // Binance最小下单量：1 XAU
}

/**
 * XAU转换为Lot
 * @param {number} xau - XAU数量
 * @returns {number} Lot数量
 */
export function xauToLot(xau) {
  if (xau === null || xau === undefined || isNaN(xau)) {
    return 0
  }
  return Number((xau / QUANTITY_CONVERSION.XAU_PER_LOT).toFixed(QUANTITY_CONVERSION.LOT_PRECISION))
}

/**
 * Lot转换为XAU
 * @param {number} lot - Lot数量
 * @returns {number} XAU数量
 */
export function lotToXau(lot) {
  if (lot === null || lot === undefined || isNaN(lot)) {
    return 0
  }
  return Math.round(lot * QUANTITY_CONVERSION.XAU_PER_LOT)
}

/**
 * 格式化XAU显示（带单位）
 * @param {number} xau - XAU数量
 * @returns {string} 格式化后的字符串
 */
export function formatXau(xau) {
  if (xau === null || xau === undefined || isNaN(xau)) {
    return '0 XAU'
  }
  return `${xau.toFixed(QUANTITY_CONVERSION.XAU_PRECISION)} XAU`
}

/**
 * 格式化Lot显示（带单位）
 * @param {number} lot - Lot数量
 * @returns {string} 格式化后的字符串
 */
export function formatLot(lot) {
  if (lot === null || lot === undefined || isNaN(lot)) {
    return '0.00 Lot'
  }
  return `${lot.toFixed(QUANTITY_CONVERSION.LOT_PRECISION)} Lot`
}

/**
 * 格式化XAU并显示对应的Lot（用于UI显示）
 * @param {number} xau - XAU数量
 * @returns {string} 格式化后的字符串，例如："5 XAU ≈ 0.05 Lot"
 */
export function formatXauWithLot(xau) {
  if (xau === null || xau === undefined || isNaN(xau)) {
    return '0 XAU ≈ 0.00 Lot'
  }
  const lot = xauToLot(xau)
  return `${xau.toFixed(QUANTITY_CONVERSION.XAU_PRECISION)} XAU ≈ ${lot.toFixed(QUANTITY_CONVERSION.LOT_PRECISION)} Lot`
}

/**
 * 验证XAU数量是否有效
 * @param {number} xau - XAU数量
 * @returns {Object} { valid: boolean, error: string }
 */
export function validateXau(xau) {
  if (xau === null || xau === undefined || isNaN(xau)) {
    return { valid: false, error: '数量无效' }
  }

  if (xau < QUANTITY_CONVERSION.MIN_XAU) {
    return { valid: false, error: `最小下单量为 ${QUANTITY_CONVERSION.MIN_XAU} XAU` }
  }

  return { valid: true, error: null }
}

/**
 * 验证Lot数量是否有效
 * @param {number} lot - Lot数量
 * @returns {Object} { valid: boolean, error: string }
 */
export function validateLot(lot) {
  if (lot === null || lot === undefined || isNaN(lot)) {
    return { valid: false, error: '数量无效' }
  }

  if (lot < QUANTITY_CONVERSION.MIN_LOT) {
    return { valid: false, error: `最小下单量为 ${QUANTITY_CONVERSION.MIN_LOT} Lot` }
  }

  return { valid: true, error: null }
}

/**
 * 根据平台转换数量
 * @param {number} quantity - 输入数量（XAU）
 * @param {string} platform - 平台名称 ('binance' 或 'bybit')
 * @returns {number} 转换后的数量
 */
export function convertForPlatform(quantity, platform) {
  if (platform === 'bybit') {
    return xauToLot(quantity)
  }
  return quantity  // Binance使用XAU，不需要转换
}

export default {
  QUANTITY_CONVERSION,
  xauToLot,
  lotToXau,
  formatXau,
  formatLot,
  formatXauWithLot,
  validateXau,
  validateLot,
  convertForPlatform,
}
