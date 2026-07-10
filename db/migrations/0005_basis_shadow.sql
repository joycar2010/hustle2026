-- 期现底仓 carry shadow 战绩
CREATE TABLE basis_shadow_log (
    id            BIGSERIAL PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol        TEXT NOT NULL,
    funding_daily NUMERIC(12,6),
    e_bps         NUMERIC(14,4),
    decision      TEXT NOT NULL,
    detail        JSONB
);
CREATE INDEX idx_basis_shadow_sym_ts ON basis_shadow_log (symbol, ts DESC);
