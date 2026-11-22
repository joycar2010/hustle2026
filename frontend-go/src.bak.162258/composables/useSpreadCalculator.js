/**
 * 统一的点差计算管理组件
 *
 * 点差计算公式：
 * - 反向开仓：bybit做多点差 = binance_ask - bybit_ask
 * - 反向平仓：bybit平仓点差 = binance_bid - bybit_bid
 * - 正向开仓：binance做多点差 = bybit_bid - binance_bid
 * - 正向平仓：binance平仓点差 = bybit_ask - binance_ask
 */

/**
 * 计算反向开仓点差（做多Bybit）
 * @param {number} binanceAsk - Binance卖一价
 * @param {number} bybitAsk - Bybit卖一价
 * @returns {number} 反向开仓点差
 */
export function calculateReverseOpeningSpread(binanceAsk, bybitAsk) {
  return binanceAsk - bybitAsk
}

/**
 * 计算反向平仓点差（平掉Bybit多头）
 * @param {number} binanceBid - Binance买一价
 * @param {number} bybitBid - Bybit买一价
 * @returns {number} 反向平仓点差
 */
export function calculateReverseClosingSpread(binanceBid, bybitBid) {
  return binanceBid - bybitBid
}

/**
 * 计算正向开仓点差（做多Binance）
 * @param {number} bybitBid - Bybit买一价
 * @param {number} binanceBid - Binance买一价
 * @returns {number} 正向开仓点差
 */
export function calculateForwardOpeningSpread(bybitBid, binanceBid) {
  return bybitBid - binanceBid
}

/**
 * 计算正向平仓点差（平掉Binance多头）
 * @param {number} bybitAsk - Bybit卖一价
 * @param {number} binanceAsk - Binance卖一价
 * @returns {number} 正向平仓点差
 */
export function calculateForwardClosingSpread(bybitAsk, binanceAsk) {
  return bybitAsk - binanceAsk
}

/**
 * 计算所有点差（从市场数据对象）
 * @param {Object} marketData - 市场数据对象
 * @param {number} marketData.binance_bid - Binance买一价
 * @param {number} marketData.binance_ask - Binance卖一价
 * @param {number} marketData.bybit_bid - Bybit买一价
 * @param {number} marketData.bybit_ask - Bybit卖一价
 * @returns {Object} 包含所有点差的对象
 */
export function calculateAllSpreads(marketData) {
  if (!marketData) {
    return {
      reverseOpening: 0,
      reverseClosing: 0,
      forwardOpening: 0,
      forwardClosing: 0
    }
  }

  const { binance_bid, binance_ask, bybit_bid, bybit_ask } = marketData

  return {
    // 反向开仓：bybit做多点差 = binance_ask - bybit_ask
    reverseOpening: calculateReverseOpeningSpread(binance_ask, bybit_ask),

    // 反向平仓：bybit平仓点差 = binance_bid - bybit_bid
    reverseClosing: calculateReverseClosingSpread(binance_bid, bybit_bid),

    // 正向开仓：binance做多点差 = bybit_bid - binance_bid
    forwardOpening: calculateForwardOpeningSpread(bybit_bid, binance_bid),

    // 正向平仓：binance平仓点差 = bybit_ask - binance_ask
    forwardClosing: calculateForwardClosingSpread(bybit_ask, binance_ask)
  }
}

/**
 * 计算买卖价差（单一交易所）
 * @param {number} ask - 卖一价
 * @param {number} bid - 买一价
 * @returns {number} 买卖价差
 */
export function calculateBidAskSpread(ask, bid) {
  return ask - bid
}

/**
 * 从历史数据项计算点差
 * @param {Object} item - 历史数据项
 * @param {Object} item.binance_quote - Binance报价
 * @param {Object} item.bybit_quote - Bybit报价
 * @returns {Object} 包含所有点差的对象
 */
export function calculateSpreadsFromHistoryItem(item) {
  if (!item || !item.binance_quote || !item.bybit_quote) {
    return {
      reverseOpening: 0,
      reverseClosing: 0,
      forwardOpening: 0,
      forwardClosing: 0
    }
  }

  return calculateAllSpreads({
    binance_bid: item.binance_quote.bid_price || item.binance_quote.bid,
    binance_ask: item.binance_quote.ask_price || item.binance_quote.ask,
    bybit_bid: item.bybit_quote.bid_price || item.bybit_quote.bid,
    bybit_ask: item.bybit_quote.ask_price || item.bybit_quote.ask
  })
}

export default {
  calculateReverseOpeningSpread,
  calculateReverseClosingSpread,
  calculateForwardOpeningSpread,
  calculateForwardClosingSpread,
  calculateAllSpreads,
  calculateBidAskSpread,
  calculateSpreadsFromHistoryItem
}
