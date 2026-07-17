-- MIX-V6.2-PATCH-02-REV2 §4A 身份份额最小切分(份额权威留 mix_main,不搬 dcm_main)。
-- 目标:把"登录身份≠操作权限≠查看范围≠投资份额"四事实切开——本批最小集=
--   client_party(真实客户/受益主体) + portfolio_access_grant(登录账号→组合查看授权)。
-- share_account 从直挂 login_user_id 改为挂 client_id;login_user_id 保留兼容,授权走 grant。
-- 运行时由 investor.ensure_client_seed() 幂等保障;本文件为迁移记录。
-- forward-fix:三者均为身份/授权,停用置 status;绝不物理删除客户/份额/授权(§4A.5)。

CREATE TABLE IF NOT EXISTS client_party (
    client_id BIGSERIAL PRIMARY KEY,
    client_type TEXT NOT NULL DEFAULT 'CORE_POOL'
        CHECK (client_type IN ('CORE_POOL','SMA','HOUSE_RND')),
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','frozen','closed')),
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS portfolio_access_grant (
    id BIGSERIAL PRIMARY KEY,
    auth_subject_id BIGINT NOT NULL,          -- mix_users.id(登录账号)
    client_id BIGINT NOT NULL REFERENCES client_party(client_id),
    portfolio_id TEXT NOT NULL DEFAULT 'CORE_POOL',
    permissions TEXT NOT NULL DEFAULT 'read', -- read | read+confirm(账目确认)
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','revoked')),
    expires_at TIMESTAMPTZ,
    granted_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(auth_subject_id, client_id, portfolio_id));
CREATE INDEX IF NOT EXISTS idx_pag_subject ON portfolio_access_grant (auth_subject_id) WHERE status='active';

-- share_account 挂 client_id(投资份额归属客户主体,非登录账号)
ALTER TABLE share_account ADD COLUMN IF NOT EXISTS client_id BIGINT REFERENCES client_party(client_id);
CREATE INDEX IF NOT EXISTS idx_sa_client ON share_account (client_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON client_party, portfolio_access_grant TO mix_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mix_app;
