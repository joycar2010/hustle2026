-- MIX-V6.2-PATCH-01 §11:canonical 别名 / AiCoin 映射 / C2.P 研判案件。
-- 只新增,不删除旧 AiCoin(lab_case)数据;旧研判经 /research/cases adapter 只读映射。
-- 运行时由 app/routers/research.py 的 CREATE TABLE IF NOT EXISTS 保障;本文件为迁移记录。
-- 部署: sudo -u postgres psql -d mix_main -f 0010_v62_research.sql
-- 回滚(forward-fix): 三表均无生产事实依赖引擎,DROP 安全;c2p_research_decision 为证据账,
--   不做破坏性回滚——弃用时置 status='EXPIRED' 保留。

CREATE TABLE IF NOT EXISTS instrument_alias (
    alias TEXT PRIMARY KEY,
    canonical_underlying TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS aicoin_symbol_mapping (
    canonical_underlying TEXT PRIMARY KEY,
    db_key TEXT NOT NULL,
    display TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'auto',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS c2p_research_decision (
    id BIGSERIAL PRIMARY KEY,
    work_item_id TEXT NOT NULL DEFAULT '',
    proposal_id BIGINT,
    canonical_symbol TEXT NOT NULL,
    product_code TEXT NOT NULL DEFAULT 'C2.P',
    review_mode TEXT NOT NULL DEFAULT 'QUICK' CHECK (review_mode IN ('QUICK','FULL')),
    market_stage TEXT NOT NULL DEFAULT '',
    confidence_level TEXT NOT NULL DEFAULT '',
    evidence_for JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_against JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision TEXT NOT NULL DEFAULT 'OBSERVE' CHECK (decision IN ('OBSERVE','PREPARE_PLAN','REJECT')),
    next_watch_trigger TEXT NOT NULL DEFAULT '',
    thesis_invalidation TEXT NOT NULL DEFAULT '',
    recommended_route TEXT NOT NULL DEFAULT '',
    recommended_notional NUMERIC,
    max_holding_time TEXT NOT NULL DEFAULT '',
    review_at TIMESTAMPTZ,
    summary_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','COMPLETED','EXPIRED')),
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_c2p_research_sym ON c2p_research_decision (canonical_symbol, id DESC);

-- GRANT 铁律(新表须 GRANT + 序列,QH/mix 两次踩坑)
GRANT SELECT, INSERT, UPDATE, DELETE ON instrument_alias, aicoin_symbol_mapping, c2p_research_decision TO mix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mix_app;
