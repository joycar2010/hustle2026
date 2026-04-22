// Global trading pair state — shared across all dashboard components
// Uses sessionStorage so each browser tab can have its own pair selection.
// Pair list is loaded dynamically from /api/v1/hedging/pairs so it reflects
// whatever admin configured in admin/hedging — fallback to the old hardcoded
// set if the API is unreachable on first paint.
import { ref, watch, computed, reactive } from 'vue'
import api from '@/services/api'

const STORAGE_KEY = 'hustle_trading_pair'

const currentPair = ref(sessionStorage.getItem(STORAGE_KEY) || 'XAU')
watch(currentPair, (val) => { sessionStorage.setItem(STORAGE_KEY, val) })

// Hardcoded fallback — only used before the API call resolves (or if it fails).
const DEFAULT_PAIRS = [
  { code: 'XAU',   label: 'XAU',   binance: 'XAUUSDT',    mt5: 'XAUUSD+',  platform: 'Bybit',      conversionFactor: 100,  unitA: 'XAU',   unitB: 'Lot' },
  { code: 'XAG',   label: 'XAG',   binance: 'XAGUSDT',    mt5: 'XAGUSD',   platform: 'ICMarkets',  conversionFactor: 500,  unitA: 'XAG',   unitB: 'Lot' },
  { code: 'BZ',    label: 'BZ',    binance: 'BZUSDT',     mt5: 'XBRUSD',   platform: 'ICMarkets',  conversionFactor: 1000, unitA: 'BBL',   unitB: 'Lot' },
  { code: 'CL',    label: 'CL',    binance: 'CLUSDT',     mt5: 'XTIUSD',   platform: 'ICMarkets',  conversionFactor: 1000, unitA: 'BBL',   unitB: 'Lot' },
  { code: 'NG',    label: 'NG',    binance: 'NATGASUSDT', mt5: 'XNGUSD',   platform: 'ICMarkets',  conversionFactor: 1000, unitA: 'mmBtu', unitB: 'Lot' },
  { code: 'BXAU',  label: 'BXAU',  binance: 'XAUUSDT',    mt5: 'XAUUSD+',  platform: 'Bybit',      conversionFactor: 100,  unitA: 'oz',    unitB: 'Lot' },
  { code: 'ICXAU', label: 'ICXAU', binance: 'XAUUSDT',    mt5: 'XAUUSD',   platform: 'ICMarkets',  conversionFactor: 100,  unitA: 'XAU',   unitB: 'Lot' },
]

// Reactive array so Vue re-renders dropdowns when the API response lands.
export const TRADING_PAIRS = reactive([...DEFAULT_PAIRS])

let _loaded = false
let _loading = null

export async function reloadTradingPairs() {
  if (_loading) return _loading
  _loading = (async () => {
    try {
      const r = await api.get('/api/v1/hedging/pairs')
      const items = (r.data || [])
        .filter(p => p.is_active !== false)
        .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.pair_code.localeCompare(b.pair_code))
        .map(p => ({
          code: p.pair_code,
          label: p.pair_code,
          binance: p.symbol_a?.symbol || '',
          mt5:     p.symbol_b?.symbol || '',
          platform: p.platform_b?.display_name || p.platform_b?.platform_name || '',
          platformA: p.platform_a?.display_name || p.platform_a?.platform_name || '',
          conversionFactor: Number(p.conversion_factor) || 1,
          unitA: p.symbol_a?.qty_unit || '',
          unitB: p.symbol_b?.qty_unit || 'Lot',
        }))
      if (items.length) {
        TRADING_PAIRS.splice(0, TRADING_PAIRS.length, ...items)
        _loaded = true
      }
    } catch (e) {
      // keep DEFAULT_PAIRS on failure; retry on next call
    } finally {
      _loading = null
    }
  })()
  return _loading
}

// Fire on module import — non-blocking. First render uses DEFAULT_PAIRS,
// subsequent reactive re-renders pick up the full list.
reloadTradingPairs()

const pairConfig = computed(() =>
  TRADING_PAIRS.find(p => p.code === currentPair.value) || TRADING_PAIRS[0] || DEFAULT_PAIRS[0]
)

export function useTradingPair() {
  return {
    currentPair,
    pairConfig,
    getPairConfig: (code) => TRADING_PAIRS.find(p => p.code === code) || TRADING_PAIRS[0] || DEFAULT_PAIRS[0],
    TRADING_PAIRS,
    reloadTradingPairs,
  }
}
