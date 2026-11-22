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

// Filter the global TRADING_PAIRS array to just those pair_codes the current
// user has bound to BOTH an active main (A) and active hedge (B) account.
// Called after the catalog load and whenever the user reopens the navbar,
// so newly-bound pairs show up without a hard refresh.
async function _applyUserConfiguredFilter(allPairs) {
  try {
    const r = await api.get('/api/v1/pair-accounts')
    const bindings = Array.isArray(r.data) ? r.data : []
    const configured = new Set(
      bindings
        .filter(b =>
          b.account_a_id && b.account_b_id &&
          b.account_a_active !== false && b.account_b_active !== false
        )
        .map(b => b.pair_code)
    )
    if (configured.size === 0) {
      // User hasn't set up anything yet — leave the full catalog visible
      // rather than blanking the dropdown entirely (would leave them with
      // no way to navigate). They'll see warnings on selection.
      return allPairs
    }
    return allPairs.filter(p => configured.has(p.code))
  } catch {
    return allPairs
  }
}

export async function reloadTradingPairs(force = false) {
  // `force` is used when auth state changes (login / logout) — we drop any
  // in-flight load and restart so the new user's /pair-accounts is the one
  // that decides the filter.
  if (_loading && !force) return _loading
  if (force) _loading = null
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
        const visible = await _applyUserConfiguredFilter(items)
        TRADING_PAIRS.splice(0, TRADING_PAIRS.length, ...visible)
        _loaded = true
        // If the saved currentPair is no longer in the visible set, drift to
        // the first configured pair so dropdown + downstream queries align.
        if (visible.length && !visible.find(x => x.code === currentPair.value)) {
          currentPair.value = visible[0].code
        }
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
