# Sports paper module handoff

Implemented files:

- `bot/sports_markets.py`: Gamma `/markets` pagination, sports tag/slug/question detection, binary outcomes/token IDs/prices, event and league metadata, `negRisk`, tick/liquidity/volume, normalized settlement rules.
- `bot/sports_data.py`: pluggable `SportsDataSource`, market-implied fallback, static replay source, bounded Poisson win prior.
- `bot/sports_strategy.py`: conservative price/edge/exposure gate and model signal.
- `bot/sports_main.py`: `SportsPaperService` with confirmation tracking, simulated orders/decisions and `snapshot()` interface; `run_cycle(live=True)` always raises and no CLOB order imports.
- `tests/test_sports.py`: parser, source/edge/risk, paper-only invariant and Poisson tests (4 passed).
- `docs/sports-paper.md`: setup, fields, data source and integration contract.
- `.env.example` and `bot/config.py`: `SPORTS_ENABLED=false` and paper defaults.

Dashboard integration can instantiate one long-lived `SportsPaperService(cfg)` and
expose `service.snapshot()` as `/api/sports/summary`; this is read-only and does
not share or restart BTC/ETH workers.

Validation: `py -3 -m pytest tests/test_sports.py -q` => 4 passed; compileall passed.
