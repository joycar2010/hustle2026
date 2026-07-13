-- V4.0 I1 合约矩阵(方案 §7.1)——C4-C6 期限产品 + 跨保证金配平的前置。
-- 铁律:COIN-M inverse delta 须按合约乘数×价格换算,不能名义张数直接与 linear 配平。
-- 部署: sudo -u postgres psql -d mix_main -f 0005_instrument_spec.sql
CREATE TABLE IF NOT EXISTS instrument_spec (
    venue               TEXT NOT NULL,
    instrument_id       TEXT NOT NULL,          -- 交易所原生 symbol(BTCUSDT / BTCUSD_PERP / BTCUSDT_250926)
    canonical_underlying TEXT NOT NULL,         -- 归一标的(BTC),跨所配对用
    market_type         TEXT NOT NULL,          -- spot | perp | future(交割)
    linear_or_inverse   TEXT NOT NULL DEFAULT 'linear',  -- linear(U本位) | inverse(币本位)
    contract_multiplier NUMERIC(30,10) NOT NULL DEFAULT 1,  -- 每张合约面值(COIN-M=contractSize)
    quote_asset         TEXT NOT NULL DEFAULT '',
    settlement_asset    TEXT NOT NULL DEFAULT '',
    collateral_asset    TEXT NOT NULL DEFAULT '',  -- 保证金币种(inverse=base coin)
    contract_type       TEXT NOT NULL DEFAULT '',  -- PERPETUAL | CURRENT_QUARTER | NEXT_QUARTER ...
    index_definition    TEXT NOT NULL DEFAULT '',
    mark_definition     TEXT NOT NULL DEFAULT '',
    funding_interval_h  NUMERIC(8,3),           -- 永续结算周期(小时);交割为 NULL
    cap                 NUMERIC(20,8),          -- funding cap
    floor               NUMERIC(20,8),          -- funding floor
    expiry              TIMESTAMPTZ,            -- 交割到期;永续为 NULL
    delivery_price_rule TEXT NOT NULL DEFAULT '',
    settlement_time     TEXT NOT NULL DEFAULT '',
    position_mode       TEXT NOT NULL DEFAULT '',
    min_qty             NUMERIC(30,10),
    tick_size           NUMERIC(30,12),
    fee_tier            TEXT NOT NULL DEFAULT '',
    deposit_withdraw_status TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT '',   -- TRADING / BREAK / SETTLING
    raw                 JSONB,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (venue, instrument_id)
);
CREATE INDEX IF NOT EXISTS idx_instr_underlying ON instrument_spec (canonical_underlying, market_type);
CREATE INDEX IF NOT EXISTS idx_instr_expiry ON instrument_spec (expiry) WHERE expiry IS NOT NULL;
GRANT SELECT, INSERT, UPDATE, DELETE ON instrument_spec TO mix_app;
