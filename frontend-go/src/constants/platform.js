/**
 * PlatformId — single source of truth for platform identifiers across the frontend.
 *
 * Keep in lock-step with backend `app/core/platform.py::PlatformId`. The integer
 * values are a DB contract (accounts.platform_id smallint FK → platforms.platform_id).
 *
 *  Business code MUST use `PlatformId.BINANCE` etc — NEVER bare numeric literals like
 *  `platform_id === 1`, and NEVER bare strings like `"binance"`. Magic values rot.
 *
 *  Helpers:
 *   - `platformKey(pid)`   → canonical lowercase key used by varchar columns / API bodies
 *   - `platformFromKey(v)` → coerce any shape (int / "binance" / "1" / "Bybit") to enum id
 *   - `isBinance(pid)` / `isHedge(pid)` — one-liners for templates
 */

export const PlatformId = Object.freeze({
  BINANCE: 1,
  BYBIT: 2,
  IC_MARKETS: 3,
  GATE: 4,
});

const _ID_TO_KEY = Object.freeze({
  [PlatformId.BINANCE]: 'binance',
  [PlatformId.BYBIT]: 'bybit',
  [PlatformId.IC_MARKETS]: 'ic_markets',
  [PlatformId.GATE]: 'gate',
});

const _KEY_TO_ID = Object.freeze({
  binance: PlatformId.BINANCE,
  bybit: PlatformId.BYBIT,
  mt5: PlatformId.BYBIT,           // legacy alias surfaced by historical API responses
  ic_markets: PlatformId.IC_MARKETS,
  icmarkets: PlatformId.IC_MARKETS,
  ic: PlatformId.IC_MARKETS,
  gate: PlatformId.GATE,
  gate_io: PlatformId.GATE,
  gateio: PlatformId.GATE,
});

/** Return the canonical lowercase key (matches backend orders.platform / platforms.platform_name). */
export function platformKey(pid) {
  return _ID_TO_KEY[pid] ?? null;
}

/** Accept any input shape (int, numeric string, name string, enum id) and return PlatformId or null. */
export function platformFromKey(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') {
    return Object.values(PlatformId).includes(v) ? v : null;
  }
  const s = String(v).trim().toLowerCase();
  if (!s) return null;
  if (/^\d+$/.test(s)) {
    const n = parseInt(s, 10);
    return Object.values(PlatformId).includes(n) ? n : null;
  }
  return _KEY_TO_ID[s] ?? null;
}

/** Display strings used across UI — centralize to avoid inconsistent translations. */
export const PLATFORM_DISPLAY = Object.freeze({
  [PlatformId.BINANCE]: '主账号',
  [PlatformId.BYBIT]: '对冲账户',
  [PlatformId.IC_MARKETS]: '对冲账户',
  [PlatformId.GATE]: 'Gate',
});

export const isBinance = (pid) => pid === PlatformId.BINANCE;
export const isHedge   = (pid) => pid === PlatformId.BYBIT || pid === PlatformId.IC_MARKETS;
