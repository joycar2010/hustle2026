import assert from 'node:assert/strict'
import { masterFuturesUsdt } from '../src/lib/masterFutures.ts'

const live = { futures_total_balance: '686', futures_available: '686',
  futures_usdt_wallet: '580.62644022', futures_usdt_available: '686.15608250',
  futures_usdt_initial_margin: '0', futures_usdt_transferable: '580.62644022' }
assert.deepEqual(masterFuturesUsdt(live), { total: 580.62644022, margin: 0, available: 580.62644022 })
assert.equal(masterFuturesUsdt({ ...live, futures_usdt_transferable: '0' }).available, 0)
assert.deepEqual(masterFuturesUsdt({ ...live, futures_usdt_initial_margin: '100', futures_usdt_transferable: '480' }),
  { total: 580.62644022, margin: 100, available: 480 })
assert(Number.isNaN(masterFuturesUsdt({ futures_total_balance: '686', futures_available: '686' }).total))
assert(Number.isNaN(masterFuturesUsdt(null).available))
console.log('Master USDT display checks passed')
