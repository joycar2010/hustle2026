export interface MasterUsdtFields {
  futures_usdt_wallet?: string | number | null
  futures_usdt_initial_margin?: string | number | null
  futures_usdt_transferable?: string | number | null
}

// Shared by desktop/mobile headers and master-account panels. Do not fall
// back to multi-asset collateral valuations when USDT telemetry is missing.
export function masterFuturesUsdt(data: MasterUsdtFields | null | undefined) {
  const number = (value: string | number | null | undefined): number => {
    if (value == null || value === '') return NaN
    const result = Number(value)
    return Number.isFinite(result) ? result : NaN
  }
  return {
    total: number(data?.futures_usdt_wallet),
    margin: number(data?.futures_usdt_initial_margin),
    available: number(data?.futures_usdt_transferable),
  }
}
