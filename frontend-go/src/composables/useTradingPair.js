// Global trading pair state — shared across all dashboard components
// Uses sessionStorage so each browser tab can have its own pair selection
import { ref, watch, computed } from 'vue'

const STORAGE_KEY = 'hustle_trading_pair'

// Single shared reactive instance (module-level singleton)
const currentPair = ref(sessionStorage.getItem(STORAGE_KEY) || 'XAU')

watch(currentPair, (val) => {
  sessionStorage.setItem(STORAGE_KEY, val)
})

// All active pairs with display labels, symbol mappings, and conversion factors
// conversionFactor: how many A-side units per 1 B-side lot
// unitA: A-side quantity unit name
// unitB: B-side quantity unit name
export const TRADING_PAIRS = [
  { code: 'XAU',   label: 'XAU',   binance: 'XAUUSDT',    mt5: 'XAUUSD+',  platform: 'Bybit',      conversionFactor: 100,  unitA: 'XAU',   unitB: 'Lot' },
  { code: 'XAG',   label: 'XAG',   binance: 'XAGUSDT',    mt5: 'XAGUSD',   platform: 'ICMarkets',  conversionFactor: 500,  unitA: 'XAG',   unitB: 'Lot' },
  { code: 'BZ',    label: 'BZ',    binance: 'BZUSDT',     mt5: 'XBRUSD',   platform: 'ICMarkets',  conversionFactor: 1000, unitA: 'BBL',   unitB: 'Lot' },
  { code: 'CL',    label: 'CL',    binance: 'CLUSDT',     mt5: 'XTIUSD',   platform: 'ICMarkets',  conversionFactor: 1000, unitA: 'BBL',   unitB: 'Lot' },
  { code: 'NG',    label: 'NG',    binance: 'NATGASUSDT', mt5: 'XNGUSD',   platform: 'ICMarkets',  conversionFactor: 1000, unitA: 'mmBtu', unitB: 'Lot' },
  { code: 'BXAU',  label: 'BXAU',  binance: 'XAUUSDT',    mt5: 'XAUUSD+',  platform: 'Bybit',      conversionFactor: 100,  unitA: 'oz',    unitB: 'Lot' },
  { code: 'ICXAU', label: 'ICXAU', binance: 'XAUUSDT',    mt5: 'XAUUSD',   platform: 'ICMarkets',  conversionFactor: 100,  unitA: 'XAU',   unitB: 'Lot' },
]

// Module-level computed — reactive to currentPair changes, shared across all callers
const pairConfig = computed(() =>
  TRADING_PAIRS.find(p => p.code === currentPair.value) || TRADING_PAIRS[0]
)

export function useTradingPair() {
  return {
    currentPair,
    pairConfig,           // computed ref: use pairConfig.value.mt5 in JS, pairConfig.mt5 in template
    getPairConfig: (code) => TRADING_PAIRS.find(p => p.code === code) || TRADING_PAIRS[0],
    TRADING_PAIRS,
  }
}
