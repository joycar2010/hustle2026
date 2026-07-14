-- 0008: accounts_registry 加 book 列(V5 §2.1 三类资金边界隔离)。
-- CORE_POOL=共享组合投资资金 / HOUSE_RND=自有研发资金(canary/shadow/DEX,损益不进用户收益) /
-- SMA=大客户独立托管 / TEST=当前测试账户。G0 入金前:新资金账户标 CORE_POOL,与测试账户物理隔离。
ALTER TABLE accounts_registry ADD COLUMN IF NOT EXISTS book TEXT NOT NULL DEFAULT 'TEST';
-- 约束仅记录性(不强制枚举,便于将来扩 SMA:<client_id>);索引供按 book 聚合。
CREATE INDEX IF NOT EXISTS idx_accounts_registry_book ON accounts_registry(book);
