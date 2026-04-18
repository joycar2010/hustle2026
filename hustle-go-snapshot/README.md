# hustle-go snapshot — OpenCLAW go2.5 (20260419)

Source tree snapshot of /data/hustle-go at the tagged release.
The live hustle-go repo is not under git version control, so this folder
captures the source files modified/added during the OpenCLAW multi-pair
spread upgrade.

Key changes vs pre-OpenCLAW baseline:
- internal/market/gate_tick.go  NEW: Gate USDT-perp REST ticker with 1s cache
- internal/market/spread.go     UPDATED: per-pair A-side routing via APlatformID
                                (1=Binance WS, 4=Gate REST)
- internal/market/market_handlers.go UPDATED: accepts both ?pair= and ?pair_code=
- internal/pairs/pairs.go       UPDATED: PairConfig gains APlatformID column

Build:
  cd /path/to/hustle-go
  go build -o hustle-go ./cmd/server
