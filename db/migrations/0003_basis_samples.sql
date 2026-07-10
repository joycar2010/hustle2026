-- 连续基差采样:basis-sampler 持续记录活跃路由∪在场持仓的基差(gap),
-- 供基差止损历史分位用——比 shadow_log 覆盖更全(不受 route off 影响)。
CREATE TABLE dualperp_basis_samples (
    id           BIGSERIAL PRIMARY KEY,
    symbol       TEXT NOT NULL,
    venue_long   TEXT NOT NULL,
    venue_short  TEXT NOT NULL,
    basis_bps    NUMERIC(14,4) NOT NULL,   -- (空腿bid-多腿ask)/多腿ask,与 shadow_log.gap_bps 同口径
    ts           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_basis_pair_ts ON dualperp_basis_samples (symbol, venue_long, venue_short, ts DESC);
