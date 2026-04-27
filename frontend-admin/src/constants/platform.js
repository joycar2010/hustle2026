/**
 * PlatformId — single source of truth for platform identifiers across the admin frontend.
 *
 * Keep in lock-step with backend `app/core/platform.py::PlatformId` and with the user
 * frontend's `frontend/src/constants/platform.js`. The integer values are a DB contract
 * (accounts.platform_id smallint FK → platforms.platform_id).
 *
 *  Business code MUST use `PlatformId.BINANCE` etc — NEVER bare numeric literals like
 *  `platform_id === 1`, and NEVER bare strings like `"binance"`. Magic values rot.
 */

export const PlatformId = Object.freeze({
  BINANCE: 1,
  BYBIT: 2,
  IC_MARKETS: 3,
  GATE: 4,
  OKX: 5,
  BITGET: 6,
});

const _ID_TO_KEY = Object.freeze({
  [PlatformId.BINANCE]: 'binance',
  [PlatformId.BYBIT]: 'bybit',
  [PlatformId.IC_MARKETS]: 'ic_markets',
  [PlatformId.GATE]: 'gate',
  [PlatformId.OKX]: 'okx',
  [PlatformId.BITGET]: 'bitget',
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
  okx: PlatformId.OKX,
  bitget: PlatformId.BITGET,
  bg: PlatformId.BITGET,
});

export function platformKey(pid) {
  return _ID_TO_KEY[pid] ?? null;
}

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

export const PLATFORM_DISPLAY = Object.freeze({
  [PlatformId.BINANCE]: '主账号',
  [PlatformId.BYBIT]: '对冲账户',
  [PlatformId.IC_MARKETS]: '对冲账户',
  [PlatformId.GATE]: 'Gate',
  [PlatformId.OKX]: 'OKX',
  [PlatformId.BITGET]: 'Bitget',
});

export const isBinance = (pid) => pid === PlatformId.BINANCE;
export const isHedge   = (pid) => pid === PlatformId.BYBIT || pid === PlatformId.IC_MARKETS;
