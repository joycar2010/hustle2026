-- V4.0 catalog v2:产品/能力目录(方案 §3)——product_id / priority / stage / book 分开保存。
-- 取代旧 S1-S6 口径:旧码作为 alias_scode 保留供历史互查,不改历史记录。
-- 部署: sudo -u postgres psql -d mix_main -f 0004_product_catalog.sql
CREATE TABLE IF NOT EXISTS product_catalog (
    product_id   TEXT PRIMARY KEY,          -- C1/C2/C2.H/O1/I1/R1/D1.STABLE ...
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'product' CHECK (kind IN ('product','capability','phase','subtype')),
    parent_id    TEXT,                       -- C2.H 的 parent=C2;phase/subtype 不建独立持仓 owner
    economic_structure TEXT NOT NULL DEFAULT '',
    stage        TEXT NOT NULL DEFAULT 'RESEARCH'
                 CHECK (stage IN ('RESEARCH','SHADOW','CANARY','ARMED_CORE','CLOSE_ONLY','KILLED','NA')),
    priority     TEXT NOT NULL DEFAULT 'P2' CHECK (priority IN ('P0','P1','P2','P3','NA')),
    book_eligibility TEXT NOT NULL DEFAULT 'HOUSE_RND'
                 CHECK (book_eligibility IN ('HOUSE_RND','CORE_POOL','BOTH','NA')),
    deploy_domain TEXT NOT NULL DEFAULT '',  -- prod-B / D-lab / coin-py(临时)
    alias_scode  TEXT NOT NULL DEFAULT '',   -- 旧 S 码互查(S1..S6)
    sort_order   INT NOT NULL DEFAULT 100,
    note         TEXT NOT NULL DEFAULT '',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON product_catalog TO mix_app;

-- 种子(阶段/优先级取方案 §3.1/§4 的迁移期权威状态)
INSERT INTO product_catalog
(product_id,name,kind,parent_id,economic_structure,stage,priority,book_eligibility,deploy_domain,alias_scode,sort_order,note) VALUES
-- CEX 收益产品
('C1','期现收费(Spot-Perp Carry)','product',NULL,'现货多+永续空,收funding,可叠加真实earn','CANARY','P1','CORE_POOL','prod-B','S1',10,'XVG真金链路已通,账本闭合前不扩币'),
('C2','跨所费差(Perp-Perp Relative Carry)','product',NULL,'异所同币永续多空,收funding差+signed basis','CLOSE_ONLY','P1','CORE_POOL','prod-B','S2',20,'遗留pair close-only,-25U已拆账;统一Owner/Saga后恢复'),
('C2.H','HARVEST 收割','phase','C2','收割已存在且保守可持续的资金费差','SHADOW','P1','CORE_POOL','prod-B','',21,'C2首个恢复真钱phase,微型canary'),
('C2.P','PRE_CARRY 预判','phase','C2','低点差阶段预判funding/basis扩张','RESEARCH','P2','HOUSE_RND','prod-B','',22,'人工LAB,仅HOUSE_RND,不自动armed'),
('C2.C','CONVERGENCE 收敛','phase','C2','跨所基差分位与收敛','SHADOW','P2','HOUSE_RND','prod-B','',23,'与HARVEST分开归因'),
('C3','借币点差(Borrow-SpotShort-PerpLong)','product',NULL,'借币卖现货+永续多头对冲','CANARY','P1','CORE_POOL','coin-py','S3',30,'coin存量,接统一Intent后canary'),
('C3.S','Spread Carry 点差','phase','C3','借币现货开/平点差为主','CANARY','P1','CORE_POOL','coin-py','',31,'保留现有coin逻辑'),
('C3.R','Rate Carry 利率','phase','C3','signed funding+借息+earn净额','SHADOW','P1','CORE_POOL','coin-py','',32,'修正signed funding后作C3路由'),
('C4','期现交割(Spot-Future)','product',NULL,'现货与交割合约,到期硬锚','RESEARCH','P1','CORE_POOL','prod-B','',40,'新增模式第一优先,先I1'),
('C5','永续交割(Perp-Future)','product',NULL,'永续与交割,funding浮动+到期锚','RESEARCH','P1','CORE_POOL','prod-B','',50,'紧随C4'),
('C6','交割配对(Future-Future)','product',NULL,'同到期且结算兼容的交割配对','RESEARCH','P2','CORE_POOL','prod-B','',60,'完成I1后再建'),
-- 非产品能力
('O1','现金流优化器(Cashflow Optimizer)','capability',NULL,'按真实腿加funding/borrow/earn;不持仓不产生独立PnL','NA','P1','NA','prod-C','S4',70,'原三率(S4)降级为leg-aware插件,不抢仓'),
('I1','合约矩阵(Instrument Matrix)','capability',NULL,'USDT/USDC/COIN-M/linear/inverse/乘数/到期/结算规格','NA','P1','NA','prod-A','',80,'C4-C6前置工程'),
-- Onchain/DeFi(D-lab)
('R1','市场效率哨兵(Market Efficiency Sentinel)','capability',NULL,'DEX市场效率与成本标尺,只读研究','NA','P2','NA','D-lab','S5',90,'延迟套利当前架构已证伪NO-GO'),
('D1','可赎回折价(Redeemable Claim Discount)','product',NULL,'可赎回稳定币/LST/ERC-4626份额折价','RESEARCH','P2','HOUSE_RND','D-lab','',100,'测试机;先验证真实赎回'),
('D1.STABLE','稳定币赎回折价','subtype','D1','可直接赎回稳定币份额','RESEARCH','P2','HOUSE_RND','D-lab','',101,''),
('D1.LST','LST赎回折价','subtype','D1','可赎回LST/原生币折价','RESEARCH','P2','HOUSE_RND','D-lab','',102,''),
('D1.VAULT','Vault份额折价','subtype','D1','ERC-4626或类vault份额折价','RESEARCH','P2','HOUSE_RND','D-lab','',103,''),
('D2','固定到期凭证(Fixed-Maturity/PT)','product',NULL,'固定到期PT或收益凭证折价','RESEARCH','P2','HOUSE_RND','D-lab','',110,'按到期NPV'),
('D3','转移结算(Transfer Settlement)','product',NULL,'DEX买入+CEX对冲+真实充值后卖出结算','RESEARCH','P2','HOUSE_RND','D-lab','',120,'重点管理在途资产'),
('D4','固定期限利差(Fixed-Term Rate Spread)','product',NULL,'同canonical asset同期限固定借贷利差','RESEARCH','P2','HOUSE_RND','D-lab','',130,'不得期限错配'),
-- 击杀:S6 做量降费(方案§21明令不刷量/自成交/未来VIP解释负edge)
('S6','做量降费(费率飞轮)·已弃','product',NULL,'元游戏刷量提VIP档','KILLED','NA','NA','','S6',140,'方案§21明令不做:不刷量/自成交/未来VIP解释负edge')
ON CONFLICT (product_id) DO NOTHING;
