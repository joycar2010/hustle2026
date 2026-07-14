-- 0009: #5 账户模式(account_mode) + 策略×账户资格矩阵(V5 §7.1/§6.1 执行模板前置)。
-- account_mode 决定执行机制:classic(经典钱包分离,C3 靠杠杆钱包空+合约钱包多+钱包间划转)
--   vs portfolio_margin(统一账户/组合保证金,交叉抵押,钱包不分离,适合借贷利率套利)。
-- 资格矩阵=策略×账户模式兼容性单一权威;opener/executor 查它门控——不硬编码"统一账户=只借贷"。

ALTER TABLE accounts_registry ADD COLUMN IF NOT EXISTS account_mode TEXT NOT NULL DEFAULT 'classic';
-- classic | portfolio_margin(统一账户) | cross_margin | isolated | unknown

-- 策略×账户模式资格矩阵。eligibility: PREFERRED(首选) | ALLOWED(允许) | FORBIDDEN(禁止)。
CREATE TABLE IF NOT EXISTS strategy_account_eligibility (
    strategy      TEXT NOT NULL,     -- 产品码 C1/C2/C3/C3R/C4/C5/C6/S4 等
    account_mode  TEXT NOT NULL,     -- classic | portfolio_margin | ...
    eligibility   TEXT NOT NULL DEFAULT 'ALLOWED',
    reason        TEXT,
    updated_by    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy, account_mode)
);

-- 默认矩阵(可后续经 UI 改):
--   C3 借币点差(BORROW_SPOT_SHORT_DERIVATIVE_LONG)=需钱包分离,classic 首选,统一账户禁止(用户政策);
--   C3R/S4 借贷利率套利=统一账户首选(交叉抵押高效),classic 允许;
--   C1/C2 期现/跨所费差=两种模式都允许。
INSERT INTO strategy_account_eligibility(strategy, account_mode, eligibility, reason, updated_by) VALUES
  ('C3',  'classic',          'PREFERRED', '借币现货空+合约多需钱包分离', 'seed'),
  ('C3',  'portfolio_margin', 'FORBIDDEN', '统一账户不跑C3(政策:统一账户专做借贷套利)', 'seed'),
  ('C3R', 'portfolio_margin', 'PREFERRED', '借贷利率套利:统一账户交叉抵押高效', 'seed'),
  ('C3R', 'classic',          'ALLOWED',   '借贷利率套利:classic 亦可', 'seed'),
  ('S4',  'portfolio_margin', 'PREFERRED', '三率利差=借贷套利,统一账户首选', 'seed'),
  ('S4',  'classic',          'ALLOWED',   NULL, 'seed'),
  ('C1',  'classic',          'ALLOWED',   NULL, 'seed'),
  ('C1',  'portfolio_margin', 'ALLOWED',   NULL, 'seed'),
  ('C2',  'classic',          'ALLOWED',   NULL, 'seed'),
  ('C2',  'portfolio_margin', 'ALLOWED',   NULL, 'seed')
ON CONFLICT (strategy, account_mode) DO NOTHING;

-- mix_app(mix-backend 写角色)授权(否则 InsufficientPrivilege)
GRANT SELECT, INSERT, UPDATE ON strategy_account_eligibility TO mix_app;
