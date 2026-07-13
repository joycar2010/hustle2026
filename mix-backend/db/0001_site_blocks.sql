-- 官网 CMS 内容区块(用户端登录框/品牌头等,site_config.brand 之外的可配区块)
-- 部署: psql -d mix_main -f 0001_site_blocks.sql  (postgres 超户执行;GRANT 是纪律,mix_app 无 DDL 权)
CREATE TABLE IF NOT EXISTS site_blocks (
    block_key  TEXT PRIMARY KEY,          -- user_login | user_brand (白名单在 ops.py)
    content    TEXT NOT NULL DEFAULT '{}',-- JSON 文本(与 site_config.brand 同口径,json.dumps 存)
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON site_blocks TO mix_app;
