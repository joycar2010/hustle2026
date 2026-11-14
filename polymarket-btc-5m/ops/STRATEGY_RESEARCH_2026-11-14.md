# Polymarket BTC 5m — verified strategies vs v1.3 bot

Research date: 2026-11-14. Sources: large-N replays, wallet reverse-engineering, GitHub OSS, Reddit autopsy. X.com indexed hits were thin; wallet tapes + empirical studies dominate.

## Verdict

Directional **late_edge taker** is structurally fee-hostile. Wallet-verified profits cluster on **split-sell market making + maker rebates**, not prediction. Our A path is correctly constrained but still the wrong primary edge. B (pair-cost maker bids) is closer economically but invents inventory by buying instead of minting, and lacks merge/redeem + sub-second cancel/replace.

## Evidence ranked

| Family | Evidence | Our bot | Notes |
|--------|----------|---------|-------|
| Split-sell MM (mint → post-only asks both) | **High** (spork30 tape, Sep ~$3.6M vol / +$8.7k / +$4.8k rebates) | Missing | Inventory from $1 mint; sell both >$1; lean≤3; merge then redeem |
| Buy-both + merge arb | High but thin | Partial | Our maker buys under `pair_cost`; no merge path |
| Lead / TWAP probability taker | High (34,559 windows) | Weak | Needs Chainlink TWAP + hold-rate table; we use spot Δ$ |
| Late favorite 0.90–0.99 | **Fails** | Banned (P0) | Matches our hard-ban |
| Binance / oracle lag taker | **Fails** (−0.4pp fillable) | Still partly chased | Consensus OK as hygiene, not as edge |

## Key numbers (public studies)

- Maker-heavy bots profitable **49%** vs taker-only **26%** (28-day / 2,500 wallets).
- At bell, 5–10 bp opening gap held **66.1%**; trade only if ask < hold WR − fee − ~3¢ margin.
- Spot lead error @ T−5s: **6.8%**; projected closing TWAP error: **0.2%**.
- Favorite ask bands on 4.6k live books: all lose after fee (e.g. 0.80–0.95 WR 84.7% vs BE 88.3%).

## Gap vs current code (v1.3)

| Layer | Current | Verified practice | Pri |
|-------|---------|-------------------|-----|
| Oracle | OKX/CB/Kraken median spot | Chainlink 60s TWAP (PolyBolt) | P3 Critical |
| Prob model | Fixed Δ$ (±25) | Lead×time hold table + vol | P3 Critical |
| Maker inventory | Buy both on CLOB | Mint complete set, then sell | P4 Critical |
| Lifecycle | Hold / flatten to resolve | Merge pairs + redeem winner | P4 High |
| Latency | REST poll ~1s | WS cancel inside 150ms taker delay | P4 High |
| Rebates | Stub ≈0 | Track rebate share | P4 Med |
| late_edge band | Cap 0.88, ban ≥0.90 | Keep | Done |
| Pair profit | ≤0.97 | Keep | Done |

## Recommended rebuild order

### P3 — make late_edge scientific (or demote it)
1. PolyBolt / Chainlink TWAP feed for price-to-beat + projected close.
2. Embed lead-hold WR table; enter only when `ask + fee + 0.03 < hold_wr`.
3. Opening-gap mode (first 30–60s) when gap ≥5 bp and book underprices.
4. Final-minute: use projected TWAP, never raw spot.

### P4 — build the wallet-verified edge
1. New `MODE=split_sell`: mint N complete sets → post-only asks both sides at fair+edge.
2. Lean clamp (≤3–10 shares); pull ahead side until lag catches up.
3. Merge remaining pairs before oracle; redeem unpaired winner.
4. WebSocket market data + cancel/replace loop targeting <150ms.
5. Real maker rebate attribution in audit.

### Keep now
- Paper maker (`pair_cost`, missing-leg, flatten) as main paper lane.
- late_edge as guarded research lane only — do not scale.
- No live until merge/redeem + WS cancel are real.

## Primary sources

- https://polymtradebot.com/blog/btc-up-or-down-5-minutes-strategy
- https://www.reddit.com/r/PredictionsMarkets/comments/1uoqskg/how_efficient_are_polymarkets_5min_crypto_markets/
- https://github.com/0xbrutusdev/polymarket-5min-crypto-trading-bot
- https://github.com/thesoulcrancerdev/poly-trading-strategies
- https://github.com/snpsnp21/polymarket-btc-5m-hedge-ladder-bot-using-maker-roles-making-decision-model
- https://github.com/jmazzini/5m-poly-bot
- https://docs.polymarket.com/trading/market-making
