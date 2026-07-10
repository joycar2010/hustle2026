-- 管理后台地基:操作员(哈希令牌+三级权限)、引擎配置(armed 从 env 迁 DB)、告警落库、审计。
-- 纪律照 route 表:显式主键 NOT NULL、无 NULL 魔法行、乐观锁 version、全量审计。

-- ① 操作员:令牌哈希存储(绝不明文——武装令牌泄露=交出真金开关)
CREATE TABLE operators (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    token_hash  TEXT NOT NULL,                 -- sha256(token) hex
    role        TEXT NOT NULL DEFAULT 'VIEWER',-- VIEWER | OPERATOR | SUPER_ADMIN
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_op_token UNIQUE (token_hash),
    CONSTRAINT ck_op_role CHECK (role IN ('VIEWER', 'OPERATOR', 'SUPER_ADMIN'))
);

-- ② 引擎配置:armed 开关/白名单/上限等,取代 systemd Environment。
--    显式 (engine, key) 主键;引擎订阅 dcm:config:updates 热重载。
CREATE TABLE engine_config (
    id          BIGSERIAL PRIMARY KEY,
    engine      TEXT NOT NULL,                 -- dualperp | basis | ...
    ckey        TEXT NOT NULL,                 -- mode | arm_symbols | max_notional_hard | ...
    cval        TEXT NOT NULL DEFAULT '',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_by  TEXT NOT NULL DEFAULT 'system',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_engine_cfg UNIQUE (engine, ckey)
);

-- ③ 告警落库:risk-ledger fire() 镜像一条,供告警历史页 + 将来 LLM 复盘
CREATE TABLE alerts_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    service     TEXT NOT NULL,
    akey        TEXT NOT NULL,
    level       TEXT NOT NULL DEFAULT 'warn',  -- info | warn | fatal
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_alerts_ts ON alerts_log (ts DESC);
CREATE INDEX idx_alerts_level ON alerts_log (level, ts DESC);

-- ④ 管理操作审计:每个写按钮留痕(谁/何时/改了什么/结果)
CREATE TABLE admin_audit (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    operator    TEXT NOT NULL,
    role        TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    payload     JSONB,
    result      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_admin_audit_ts ON admin_audit (ts DESC);
