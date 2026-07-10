-- PnL 三表(coin PnL 持久化模式移植):逐笔收入(资金费/手续费/已实现盈亏)+权益快照。
-- 纪律:交易所账单为真相源;(venue, ext_id) 唯一去重;拉取失败绝不写假数据。

-- ① 逐笔收入:各所账单归一(FUNDING/FEE/PNL)
CREATE TABLE income_records (
    id         BIGSERIAL PRIMARY KEY,
    venue      TEXT NOT NULL,
    ext_id     TEXT NOT NULL,              -- 交易所账单ID(去重键)
    symbol     TEXT NOT NULL DEFAULT '',   -- 统一符号,账户级收入为空
    itype      TEXT NOT NULL,              -- FUNDING | FEE | PNL | OTHER
    amount     NUMERIC(20,8) NOT NULL,     -- USDT,正=收入负=支出
    ts         TIMESTAMPTZ NOT NULL,
    raw        JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_income UNIQUE (venue, ext_id)
);
CREATE INDEX idx_income_ts ON income_records (ts DESC);
CREATE INDEX idx_income_sym ON income_records (symbol, itype, ts DESC);

-- ② 拉取游标:每所增量拉取的水位
CREATE TABLE income_cursors (
    venue      TEXT PRIMARY KEY,
    last_ts_ms BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ③ 权益快照:小时级逐所权益(净值曲线原料)
CREATE TABLE equity_snapshots (
    id         BIGSERIAL PRIMARY KEY,
    venue      TEXT NOT NULL,
    equity_usdt NUMERIC(18,4) NOT NULL,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_equity_ts ON equity_snapshots (venue, ts DESC);
