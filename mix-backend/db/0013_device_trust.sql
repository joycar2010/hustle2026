-- MIX-V6.2-PATCH-02-REV2 §9 受信设备立项(前置②:移动交易前置)。
-- 本批只建表+盘点契约,不开放真金移动交易;M5 shadow 层消费,armed 待 M4 完成后单独放行。
-- 受信=已受信桌面确认注册+绑定 WebAuthn 凭证+可撤销 device_session,非浏览器自报/屏幕宽度。
-- 运行时由 ops 端点 CREATE TABLE IF NOT EXISTS 保障;本文件为迁移记录。

CREATE TABLE IF NOT EXISTS trusted_operator_device (
    device_session_id TEXT PRIMARY KEY,        -- 随机不可猜;可撤销
    operator TEXT NOT NULL,
    surface TEXT NOT NULL DEFAULT 'phone'       -- tablet | phone
        CHECK (surface IN ('tablet','phone','desktop')),
    trust_state TEXT NOT NULL DEFAULT 'pending'  -- pending | trusted | revoked
        CHECK (trust_state IN ('pending','trusted','revoked')),
    webauthn_cred_id TEXT NOT NULL DEFAULT '',   -- 绑定的 Passkey 凭证(注册时写)
    label TEXT NOT NULL DEFAULT '',              -- 操作员可读设备名
    registered_by TEXT NOT NULL DEFAULT '',      -- 受信桌面确认者
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS idx_tod_operator ON trusted_operator_device (operator) WHERE trust_state='trusted';

CREATE TABLE IF NOT EXISTS operator_device_limit (
    device_session_id TEXT NOT NULL REFERENCES trusted_operator_device(device_session_id),
    scope TEXT NOT NULL DEFAULT 'GLOBAL',        -- GLOBAL | 产品(C2.P/C3.S)
    max_notional_usdt NUMERIC NOT NULL DEFAULT 0,     -- 单笔名义上限(移动端不可自行提高)
    daily_risk_budget_usdt NUMERIC NOT NULL DEFAULT 0,-- 当日移动端新增风险额度
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (device_session_id, scope));

GRANT SELECT, INSERT, UPDATE, DELETE ON trusted_operator_device, operator_device_limit TO mix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mix_app;
