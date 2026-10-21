const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const path = require('node:path');

(async () => {
  const source = fs.readFileSync(path.join(__dirname, 'pnl.ts'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
  const { assetPnl, pnlReturn } = await import('data:text/javascript;base64,' + Buffer.from(compiled.outputText).toString('base64'));
  const paper = {
    realized_usd: 3, cumulative_realized_usd: 7,
    by_asset: { BTC: { realized_usd: 1, wins: 1 }, SPORTS: { realized_usd: 2, wins: 2 } },
    cumulative_by_asset: { BTC: { realized_usd: 5, wins: 4, losses: 1 }, SPORTS: { realized_usd: 2, wins: 2 } },
  };
  assert.equal(assetPnl(paper, 'BTC', 'today').realized_usd, 1);
  assert.equal(assetPnl(paper, 'BTC', 'cumulative').realized_usd, 5);
  assert.equal(pnlReturn(assetPnl(paper, 'BTC', 'cumulative').realized_usd, 100), 5);
  assert.equal(pnlReturn(assetPnl(paper, 'BTC', 'today').realized_usd, 100), 1);
  assert.equal(assetPnl({ by_asset: {}, cumulative_by_asset: paper.cumulative_by_asset }, 'BTC', 'today').realized_usd, 0);
  assert.equal(assetPnl({ realized_usd: 3, by_asset: paper.by_asset }, 'BTC', 'cumulative'), null);
  assert.equal(assetPnl(undefined, 'BTC', 'today'), null);
  assert.equal(assetPnl({ cumulative_by_asset: {} }, 'BTC', 'cumulative').realized_usd, 0);
  assert.equal(assetPnl({ cumulative_by_asset: { BTC: { realized_usd: -2 } } }, 'BTC', 'cumulative').realized_usd, -2);
  for (const base of [0, -1, null, undefined, Infinity, NaN]) assert.equal(pnlReturn(5, base), null);
  assert.equal(pnlReturn(null, 100), null);
  assert.equal(pnlReturn(0, 100), 0);
  assert.equal(pnlReturn(-2, 100), -2);
  console.log('BTC frontend accounting selectors: all assertions passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
