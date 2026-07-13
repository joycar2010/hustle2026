/**
 * HustleCoin Mix — 零依赖 mock server（联调基线）
 * 运行：node mock/server.mjs   （默认 :8100，MIX_MOCK_PORT 可改）
 * 前端：VITE_API_BASE=http://localhost:8100/api/v1
 *
 * 语义与 contracts/openapi.yaml 对齐：
 *  - /meta/enums 是状态枚举单一来源
 *  - 写操作一律 202 + 延迟 800ms 后在 /positions 里可见变化（模拟 WS 对账）
 *  - merged/self、view/sort/dir 为必填参数，缺参返回 400（把口径错误挡在联调期）
 */
import http from 'node:http'

const PORT = process.env.MIX_MOCK_PORT || 8100

/* ---------------- fixtures（取自设计稿数据） ---------------- */
const ENUMS = {
  StrategyCode: ['S1','S2','S3','S4','S5','S6'],
  PhaseCode: ['CANDIDATE','ARBITRATING','ARMED','OPENING','HOLDING','EXITING','SETTLED','BORROWABLE','PENDING_BORROW','REPAYING','COOLDOWN_3045','FROZEN','QUOTA_CHECK','LENDING','ACCRUING','RECLAIMING','EVENT_FEED','EVALUATING','MANUAL_CONFIRM','REVERTING'],
  SubRowStateKind: ['api_error','borrowing','repay_paused','holding','plain'],
  AlertLevel: ['FATAL','WARN','INFO'],
}

const S3_LABELS = ['现-期','爆率','最大可借','现币','借币','借币金额','风险','保证金','净值']
const now = Date.now()

const positions = [
  { id:'LP-BNB', symbol:'BNBUSDT', positionCount:2, strategyCode:'S3', phase:'HOLDING', phaseLabel:'持仓·收费率',
    columnLabels:S3_LABELS,
    marketParams:[{label:'开',value:'-0.051',tone:'down'},{label:'平',value:'-0.152',tone:'down'},{label:'资',value:'0.0050',tone:'accent'},{label:'时',value:'4'},{label:'限',value:'2'},{label:'息',value:'0.133%',tone:'accent'}],
    pushStatus:'推 11 09:32', fundingRateRatio:'0.23', singleRuleBrief:'-', allowRemove:true, allowRepay:true,
    pnl:512.09, openedAt:'2026-07-11T09:32:00+08:00', keyDeadlineTs:null, ruleScope:'template',
    subRows:[
      { executingAccount:'hustle-001', accountKind:'sub', venue:'Binance', platformType:'cex',
        values:[{value:'32.15'},{value:'12.4%',tone:'up'},{value:'6,200.00',tone:'accent'},{value:'0.0000',dim:true},{value:'32.1500',tone:'strategy'},{value:'19,104.22'},{value:'2.84',tone:'up'},{value:'24,110.45'},{value:'18,205.10'}],
        econParams:[{label:'润',value:'+512.09',tone:'up'},{label:'资',value:'+381.22',tone:'up'},{label:'开',value:'0.12'},{label:'息',value:'0.133%'},{label:'累息',value:'-12.40',tone:'down'},{label:'平',value:'—'}],
        state:{kind:'holding',text:'持仓 26.8h'}, fundingRateRatio:'0.23', borrowRatePerSec:'2.0/s', banCountdown:null, apiRestricted:false, apiStatus:'ok' },
      { executingAccount:'hustle-002', accountKind:'sub', venue:'OKX', platformType:'cex',
        values:[{value:'32.15'},{value:'12.4%',tone:'up'},{value:'3,600.00',tone:'accent'},{value:'0.0000',dim:true},{value:'0.0000',dim:true},{value:'—',dim:true},{value:'999.00',tone:'up'},{value:'10,240.55'},{value:'8,412.30'}],
        econParams:null, state:{kind:'borrowing',text:'借币'}, fundingRateRatio:null, borrowRatePerSec:'1.6/s', banCountdown:null, apiRestricted:false, apiStatus:'ok' },
    ] },
  { id:'LP-LTC', symbol:'LTCUSDT', positionCount:1, strategyCode:'S3', phase:'REPAYING', phaseLabel:'还币中',
    columnLabels:S3_LABELS,
    marketParams:[{label:'开',value:'-0.048',tone:'down'},{label:'平',value:'-0.120',tone:'down'},{label:'资',value:'0.0042',tone:'accent'},{label:'时',value:'4'},{label:'限',value:'2'},{label:'息',value:'0.146%',tone:'accent'}],
    pushStatus:'推 10 22:18', fundingRateRatio:'0.18', singleRuleBrief:'-', allowRemove:true, allowRepay:true,
    pnl:96.44, openedAt:'2026-07-10T22:18:00+08:00', keyDeadlineTs:null, ruleScope:'template',
    subRows:[
      { executingAccount:'hustle-001', accountKind:'sub', venue:'Binance', platformType:'cex',
        values:[{value:'112.40'},{value:'12.4%',tone:'up'},{value:'3,412.66',tone:'accent'},{value:'112.4000'},{value:'112.4000',tone:'strategy'},{value:'9,472.19'},{value:'1.42',tone:'accent'},{value:'6,120.44'},{value:'4,208.15'}],
        econParams:[{label:'润',value:'+96.44',tone:'up'},{label:'资',value:'+122.18',tone:'up'},{label:'开',value:'0.09'},{label:'息',value:'0.146%'},{label:'累息',value:'-8.42',tone:'down'},{label:'平',value:'-0.02',tone:'down'}],
        state:{kind:'repay_paused',text:'还币暂停',resumable:true}, fundingRateRatio:'0.18', borrowRatePerSec:'1.2/s', banCountdown:'2:14', apiRestricted:false, apiStatus:'ok' },
    ] },
  { id:'LP-FIL', symbol:'FILUSDT', positionCount:1, mark:'dead', strategyCode:'S3', phase:'FROZEN', phaseLabel:'冻结',
    columnLabels:S3_LABELS,
    marketParams:[{label:'开',value:'-0.119',tone:'down'},{label:'平',value:'-0.356',tone:'down'},{label:'资',value:'0.0181',tone:'accent'},{label:'时',value:'4'},{label:'限',value:'2'},{label:'息',value:'0.226%',tone:'accent'}],
    pushStatus:'推 08 22:14', fundingRateRatio:'-0.48', singleRuleBrief:'-', allowRemove:false, allowRepay:false,
    pnl:67.21, openedAt:'2026-07-08T22:14:00+08:00', keyDeadlineTs:null, ruleScope:'override',
    subRows:[
      { executingAccount:'hustle-004', accountKind:'sub', venue:'OKX', platformType:'cex',
        values:[{value:'26.70'},{value:'12.4%',tone:'up'},{value:'—',dim:true},{value:'26.7000'},{value:'0.0000',dim:true},{value:'—',dim:true},{value:'1.08',tone:'down'},{value:'2,904.12'},{value:'1,205.40'}],
        econParams:[{label:'润',value:'+67.21',tone:'up'},{label:'资',value:'+67.21',tone:'up'},{label:'开',value:'0.14'},{label:'息',value:'0.226%'},{label:'累息',value:'-14.22',tone:'down'},{label:'平',value:'—'}],
        state:{kind:'api_error',text:'API 错误'}, fundingRateRatio:null, borrowRatePerSec:'0.4/s', banCountdown:'4:32', apiRestricted:true, apiStatus:'restricted' },
    ] },
  { id:'LP-BTC', symbol:'BTCUSDT', positionCount:1, strategyCode:'S2', phase:'HOLDING', phaseLabel:'持有',
    columnLabels:['多腿数量','空腿数量','费率差','下次结费','Delta','距强平'],
    marketParams:[{label:'E',value:'12bps',tone:'accent'},{label:'闸',value:'enforce',tone:'up'},{label:'杠',value:'10x'}],
    pushStatus:'推 10 04:12', fundingRateRatio:'0.31', singleRuleBrief:'-', allowRemove:true, allowRepay:false,
    pnl:1256.78, openedAt:'2026-07-10T04:12:00+08:00', keyDeadlineTs: now + 2*3600e3 + 18*60e3, ruleScope:'template',
    subRows:[
      { executingAccount:'hustle-001', accountKind:'sub', venue:'Binance', platformType:'cex',
        values:[{value:'0.5120'},{value:'—',dim:true},{value:'+0.0125%',tone:'up'},{value:'02:18:47',tone:'accent'},{value:'+0.00003',tone:'up'},{value:'26.5%'}],
        econParams:[{label:'润',value:'+1,256.78',tone:'up'},{label:'资',value:'+812.34',tone:'up'},{label:'ADL',value:'1'}],
        state:{kind:'holding',text:'持仓 62.1h'}, fundingRateRatio:'0.31', borrowRatePerSec:null, banCountdown:null, apiRestricted:false, apiStatus:'ok' },
      { executingAccount:'hustle-master', accountKind:'master', venue:'OKX', platformType:'cex',
        values:[{value:'—',dim:true},{value:'0.5120'},{value:'+0.0125%',tone:'up'},{value:'02:18:47',tone:'accent'},{value:'-0.00003',tone:'down'},{value:'28.1%'}],
        econParams:[{label:'润',value:'—'},{label:'资',value:'—'},{label:'ADL',value:'1'}],
        state:{kind:'holding',text:'持仓 62.1h'}, fundingRateRatio:'0.31', borrowRatePerSec:null, banCountdown:null, apiRestricted:false, apiStatus:'ok' },
    ] },
  { id:'LP-XRP', symbol:'XRPUSDT', positionCount:1, strategyCode:'S2', phase:'HOLDING', phaseLabel:'持有',
    columnLabels:['多腿数量','空腿数量','费率差','下次结费','Delta','距强平'],
    marketParams:[{label:'E',value:'12bps',tone:'accent'},{label:'闸',value:'enforce',tone:'up'},{label:'杠',value:'10x'}],
    pushStatus:'结费 00:26:12', fundingRateRatio:'-0.12', singleRuleBrief:'-', allowRemove:true, allowRepay:false,
    pnl:-138.42, openedAt:'2026-07-12T01:54:00+08:00', keyDeadlineTs: now + 26*60e3, ruleScope:'template', subRows:[] },
]

const strategies = [
  { code:'S1', name:'期现收费', layer:'底仓层', enabled:true, slots:4, notional:1240000, pnlToday:512.40, pnlTotal:48742, ePass:'62%', pipeline:{基差扫描:96,'E 仲裁':24,建仓:2,'持有·收费':4,回归监测:4,退出:8,结算:112} },
  { code:'S2', name:'跨所费差', layer:'中层主力', enabled:true, slots:12, notional:5830000, pnlToday:2104.55, pnlTotal:128714, ePass:'48%', pipeline:{费差候选:1245,'E 仲裁':532,活跃路由:86,武装门控:32,开仓中:14,'持有·结算':12,退出:18} },
  { code:'S3', name:'借币点差', layer:'存量业务', enabled:true, slots:5, notional:1120000, pnlToday:498.12, pnlTotal:34406, ePass:'54%', pipeline:{可借扫描:128,借币:8,卖出建仓:3,对冲:3,'收费率·在管':5,还币闸:2,回滚兜底:0} },
  { code:'S4', name:'三率利差', layer:'增强层', enabled:true, slots:2, notional:680000, pnlToday:182.20, pnlTotal:40141, ePass:'71%', pipeline:{利差扫描:42,额度校验:12,借入:3,'出借/申购':2,计息中:2,到期回收:1,结算:38} },
  { code:'S5', name:'事件折价', layer:'机会外挂', enabled:false, slots:1, notional:120000, pnlToday:36.80, pnlTotal:8912, ePass:'—', pipeline:{事件流:14,折价评估:3,人工确认:1,建仓:0,回归监测:1,退出:2,复盘:9} },
  { code:'S6', name:'做量降费', layer:'元游戏', enabled:true, slots:0, notional:0, pnlToday:88.15, pnlTotal:25805, ePass:'—', pipeline:{目标量测算:3,挂单:1842,成交回填:'41%',返佣结算:3,'VIP 进度':'82%',费率下调:'-0.8bp'} },
]

const accounts = [
  { id:'master-binance', kind:'master', platformType:'cex', venue:'币安', domain:'A·shard0', apiStatus:'ok',
    metrics:{净值:'1,432,999.44',可用:'512,340.00',子账户:'2',借币负债:'-532,864.32'},
    children:[
      { id:'hustle-001', kind:'sub', platformType:'cex', venue:'币安', domain:'A·shard0', apiStatus:'ok', metrics:{现货:'1,234,567.89',保证金:'2,345,678.91',负债:'-456,321.11',风险度:'32%'}, children:[] },
      { id:'hustle-007', kind:'sub', platformType:'cex', venue:'币安', domain:'A·shard0', apiStatus:'ok', metrics:{现货:'198,432.55',保证金:'432,109.87',负债:'-76,543.21',风险度:'22%'}, children:[] },
    ] },
  { id:'master-okx', kind:'master', platformType:'cex', venue:'OKX', domain:'A·shard0', apiStatus:'ok',
    metrics:{净值:'967,443.90',可用:'298,110.00',子账户:'2',借币负债:'-419,555.55'},
    children:[
      { id:'hustle-002', kind:'sub', platformType:'cex', venue:'OKX', domain:'A·shard0', apiStatus:'ok', metrics:{现货:'987,654.32',保证金:'1,876,543.21',负债:'-321,123.45',风险度:'41%'}, children:[] },
      { id:'hustle-004', kind:'sub', platformType:'cex', venue:'OKX', domain:'C·shard2', apiStatus:'restricted', metrics:{现货:'312,456.78',保证金:'654,987.12',负债:'-98,432.10',风险度:'55%'}, children:[] },
    ] },
  { id:'kms-wallet-group', kind:'master', platformType:'kms_wallet', venue:'链上域', domain:'D·dex', apiStatus:'ok',
    metrics:{总余额:'≈142,800 USDT',地址:'3',待审批:'1','KMS key':'正常'},
    children:[
      { id:'ops-hot-01', kind:'wallet', platformType:'kms_wallet', venue:'TRC20', domain:'D·dex', apiStatus:'ok', metrics:{地址:'TQx3…9f2a',余额:'84,210 USDT',KMS:'正常'}, approvalState:null, children:[] },
      { id:'ops-hot-02', kind:'wallet', platformType:'kms_wallet', venue:'ERC20', domain:'D·dex', apiStatus:'ok', metrics:{地址:'0x8c…41d7',余额:'12.42 ETH',KMS:'正常'}, approvalState:'pending_approval', children:[] },
      { id:'cold-vault', kind:'wallet', platformType:'kms_wallet', venue:'BTC', domain:'D·dex', apiStatus:'ok', metrics:{地址:'bc1q…x8k2',余额:'18.6 BTC',KMS:'冷备'}, approvalState:null, children:[] },
    ] },
]

const spreads = [
  { symbol:'ACT', open:'-0.221', close:'0.000', funding:'0.0050', dailyRate:'0.133%', net:'0.23', status:'可开' },
  { symbol:'AIGENSYN', open:'0.226', close:'-0.300', funding:'-0.0882', dailyRate:'0.258%', net:'-2.05', status:'观察' },
  { symbol:'ANKR', open:'0.831', close:'-1.141', funding:'-0.4999', dailyRate:'0.286%', net:'-10.49', status:'不可' },
  { symbol:'BEL', open:'0.058', close:'-0.300', funding:'-0.0127', dailyRate:'0.168%', net:'-0.23', status:'观察' },
  { symbol:'GUN', open:'0.000', close:'-0.272', funding:'0.0050', dailyRate:'0.146%', net:'0.21', status:'可开' },
  { symbol:'LA', open:'-0.051', close:'-0.152', funding:'0.0050', dailyRate:'0.184%', net:'0.16', status:'可开' },
]

const attribution = [
  { code:'S2', name:'跨所费差', total:128714, subjects:{ funding:98220, spread:38912, fee:-8418 } },
  { code:'S1', name:'期现收费', total:48742, subjects:{ funding:31240, spread:19822, fee:-2320 } },
  { code:'S4', name:'三率利差', total:40141, subjects:{ interest:44890, fee:-4749 } },
  { code:'S3', name:'借币点差', total:34406, subjects:{ funding:41205, interest:-5320, fee:-1479 } },
  { code:'S6', name:'做量降费', total:25805, subjects:{ rebate:31210, spread_cost:-5405 } },
  { code:'S5', name:'事件折价', total:8912, subjects:{ spread:9420, fee:-508 } },
]

const pnlDaily = [67,16,-420,29,308,477,-7,137,-63,1500,2100,-3100,1000,-16,70,566,672,-395,-1600,-31,40,54,26,-247,211,193]
  .map((v,i)=>({ date:new Date(now-(25-i)*864e5).toISOString().slice(0,10), net:v, funding:Math.round(v*0.7), spread:Math.round(v*0.4), fee:Math.round(-Math.abs(v)*0.1) }))

const userSources = [
  { key:'funding_arb', name:'资金费率套利', share:0.28 }, { key:'dualperp', name:'双合约对冲 Carry', share:0.20 },
  { key:'basis', name:'期现基差套利', share:0.17 }, { key:'lend_arb', name:'三率利差（借币反向）', share:0.14 },
  { key:'xvenue_spread', name:'跨所价差捕捉', share:0.12 }, { key:'maker_rebate', name:'做市返佣增强', share:0.09 },
]

const ledger = [
  { date:'2026-07-12', opening:'239,346.18', sysPnl:'+512.34', manualAdj:'0.00', closing:'239,858.52', chainDiff:'-12.12', status:'平' },
  { date:'2026-07-11', opening:'238,848.06', sysPnl:'+498.12', manualAdj:'0.00', closing:'239,346.18', chainDiff:'-12.12', status:'平' },
  { date:'2026-07-08', opening:'237,449.10', sysPnl:'+503.64', manualAdj:'-12.12', closing:'237,940.62', chainDiff:'-12.12', status:'调整' },
]

/* ---- 规则五级作用域（全局›策略›venue›币种›账户，就近覆盖，每作用域唯一行） ---- */
const RULE_AUDIT = []
const RULES = {
  'global': [
    { key:'kill_switch', label:'总闸 Kill Switch', value:'off', type:'switch', inherited:false },
    { key:'max_total_notional', label:'总名义上限', value:'10,000,000', unit:'USDT', inherited:false },
    { key:'leverage_cap', label:'总杠杆上限', value:'10x', inherited:false },
    { key:'blacklist_link', label:'黑名单联动', value:'on', type:'switch', inherited:false },
    { key:'alert_routing', label:'告警路由', value:'feishu + marquee', inherited:false },
  ],
  'strategy:S1': [
    { key:'e_threshold', label:'净期望 E 阈值', value:'10', unit:'bps', inherited:false },
    { key:'basis_enter', label:'基差进入', value:'25', unit:'bps', inherited:false },
    { key:'basis_exit', label:'回归离场', value:'5', unit:'bps', inherited:false },
    { key:'spot_inventory_cap', label:'最大现货库存', value:'40', unit:'%', inherited:false },
    { key:'leverage_cap', label:'杠杆上限', value:'10x', inherited:true },
  ],
  'strategy:S2': [
    { key:'e_mode', label:'E 闸模式', value:'enforce', type:'enum', options:['off','shadow','enforce'], inherited:false },
    { key:'e_threshold', label:'净期望 E 阈值', value:'12', unit:'bps', inherited:false },
    { key:'hold_to_settle', label:'持有到结算闸', value:'on', type:'switch', inherited:false },
    { key:'liq_redline', label:'距强平红线', value:'20', unit:'%', inherited:false },
    { key:'leverage_cap', label:'杠杆上限', value:'10x', inherited:true },
  ],
  'strategy:S3': [
    { key:'push_switch', label:'推送开关', value:'挂单中', type:'enum', options:['停止挂单','手动推送','挂单中'], inherited:false },
    { key:'per_uid_rate', label:'单 UID 建仓速率', value:'0.0', unit:'个/s', inherited:false },
    { key:'uid_cap', label:'UID 上限', value:'180,000', unit:'UID', inherited:false },
    { key:'contract_cap', label:'合约上限', value:'19,524', unit:'张', inherited:false },
    { key:'burst_threshold', label:'爆率阈值', value:'999.00', inherited:false },
    { key:'risk_levels', label:'风险值（主/子）', value:'10 / 18', inherited:false },
    { key:'borrow_mode', label:'借币方式', value:'okx_native', type:'enum', options:['spot_balance','cross_margin','okx_native','hybrid'], inherited:false },
    { key:'venue_quals', label:'venue 资格', value:'Binance / OKX / Bybit', inherited:false },
    { key:'cooldown_3045', label:'-3045 冷却', value:'26', unit:'h', inherited:false },
    { key:'auto_repay', label:'自动还币', value:'on', type:'switch', inherited:false },
    { key:'open_offset', label:'开仓偏移', value:'-0.221', inherited:false },
    { key:'close_offset', label:'平仓偏移', value:'0.000', inherited:false },
    { key:'funding_filter', label:'资金费过滤', value:'0.0050', inherited:false },
  ],
  'strategy:S4': [
    { key:'min_rate_spread', label:'最小年化利差', value:'4', unit:'%', inherited:false },
    { key:'principal_cap', label:'单币本金上限', value:'200,000', unit:'USDT', inherited:false },
    { key:'term_cap', label:'期限上限', value:'7', unit:'天', inherited:false },
    { key:'redeem_redline', label:'赎回排队红线', value:'2', unit:'小时', inherited:false },
  ],
  'strategy:S5': [
    { key:'discount_enter', label:'折价介入阈值', value:'0.8', unit:'%', inherited:false },
    { key:'event_cap', label:'单事件上限', value:'50,000', unit:'USDT', inherited:false },
    { key:'manual_confirm', label:'人工确认', value:'on', type:'switch', locked:true, inherited:false },
    { key:'deadpool_filter', label:'死池过滤', value:'on', type:'switch', inherited:false },
  ],
  'strategy:S6': [
    { key:'daily_quota', label:'日目标量', value:'2.4M', unit:'USDT', inherited:false },
    { key:'maker_floor', label:'maker 占比下限', value:'90', unit:'%', inherited:false },
    { key:'spread_cost_cap', label:'点差损耗上限', value:'0.4', unit:'bp', inherited:false },
    { key:'self_trade_block', label:'自成交拦截', value:'on', type:'switch', locked:true, inherited:false },
  ],
  'symbol:BNBUSDT': [
    { key:'open_offset', label:'开仓偏移', value:'-0.051', inherited:false },
    { key:'close_offset', label:'平仓偏移', value:'-0.152', inherited:false },
    { key:'e_threshold', label:'净期望 E 阈值', value:'12', unit:'bps', inherited:true },
  ],
  _fallback: (s) => [
    { key:'e_threshold', label:'净期望 E 阈值', value:'12', unit:'bps', inherited:true },
    { key:'leverage_cap', label:'杠杆上限', value:'10x', inherited:true },
  ],
}

const BLACKLIST = [
  { symbol:'FIL', source:'auto_borrow_wedge', reason:'PENDING_BORROW 僵尸回收后冻结，26.7 裸多待人工', scope:['S3','S4'], addedAt:'07-08 22:14', until:'人工解除', hits:46 },
  { symbol:'NULS', source:'announcement_delist', reason:'Gate 公告下架，联动禁开新仓', scope:['*'], addedAt:'07-12 09:31', until:'2026-07-20', hits:3 },
  { symbol:'LISTA', source:'auto_3045', reason:'连续 12 次借币失败（无券），冷却观察', scope:['S3'], addedAt:'07-11 18:05', until:'07-13 18:05', hits:28 },
  { symbol:'LUNC', source:'manual', reason:'历史风险币种，禁止所有回路', scope:['*'], addedAt:'07-02 10:12', until:'永久', hits:54 },
  { symbol:'XEM', source:'risk_trigger', reason:'单腿滑点超阈值 3 次，观察期', scope:['S2'], addedAt:'07-09 20:26', until:'07-16 20:26', hits:9 },
]
const COINS = [
  { symbol:'BTC', state:'enabled', strategies:['S1','S2','S6'], venues:'币安·OKX·Bybit·Gate·MEXC', rate8h:'+0.0125%', spreadBps:3.2, vol24h:'128.7 亿', managed:2 },
  { symbol:'ETH', state:'enabled', strategies:['S1','S2','S6'], venues:'币安·OKX·Bybit·Gate·MEXC', rate8h:'+0.0098%', spreadBps:3.8, vol24h:'89.3 亿', managed:1 },
  { symbol:'SOL', state:'enabled', strategies:['S2'], venues:'币安·OKX·Bybit·MEXC', rate8h:'+0.0152%', spreadBps:4.5, vol24h:'45.2 亿', managed:1 },
  { symbol:'BNB', state:'enabled', strategies:['S2','S3'], venues:'币安·OKX·Gate', rate8h:'+0.0121%', spreadBps:5.1, vol24h:'32.1 亿', managed:1 },
  { symbol:'XRP', state:'watch', strategies:['S2'], venues:'币安·OKX·Bybit·Gate', rate8h:'-0.0034%', spreadBps:6.2, vol24h:'53.2 亿', managed:1 },
  { symbol:'DOGE', state:'enabled', strategies:['S4'], venues:'币安·OKX·Bybit·MEXC', rate8h:'+0.0087%', spreadBps:5.8, vol24h:'22.8 亿', managed:1 },
  { symbol:'FIL', state:'frozen', strategies:['S3'], venues:'币安·OKX', rate8h:'+0.0210%', spreadBps:9.4, vol24h:'8.4 亿', managed:1 },
  { symbol:'LISTA', state:'watch', strategies:['S3'], venues:'币安·Gate', rate8h:'+0.0480%', spreadBps:12.6, vol24h:'3.1 亿', managed:0 },
  { symbol:'AVAX', state:'enabled', strategies:['S2'], venues:'OKX·Bybit·Gate', rate8h:'+0.0102%', spreadBps:6.8, vol24h:'9.8 亿', managed:1 },
  { symbol:'NULS', state:'delisted', strategies:[], venues:'Gate（下架中）', rate8h:'—', spreadBps:null, vol24h:'0.4 亿', managed:0 },
]
const NOTIFY = { channels:['feishu','marquee'], intervalSec:300, maxPerHour:6, cooldownSec:600, tokenBucket:{rate:1,burst:3} }

/* ---------------- server ---------------- */
const pendingActions = [] // {at, action, id, accountId} — 800ms 后可在 /positions 观察到 phase 变化（模拟 WS 对账）

const J = (res, code, body) => {
  res.writeHead(code, { 'content-type':'application/json; charset=utf-8', 'access-control-allow-origin':'*', 'access-control-allow-headers':'*', 'access-control-allow-methods':'*' })
  res.end(JSON.stringify(body))
}
const need = (q, res, ...keys) => {
  for (const k of keys) if (!q.get(k)) { J(res,400,{error:`missing required query: ${k}（口径必须显式）`}); return false }
  return true
}

http.createServer(async (req,res)=>{
  if (req.method==='OPTIONS') return J(res,204,{})
  const u = new URL(req.url,'http://x'); const p = u.pathname.replace(/^\/api\/v1/,''); const q = u.searchParams
  let body=''; for await (const c of req) body+=c; const payload = body?JSON.parse(body):{}

  if (p==='/meta/enums') return J(res,200,ENUMS)
  if (p==='/auth/login') return J(res,200,{token:'mock.jwt.token',user:{name:'admin',role:'operator'}})

  if (p==='/positions') {
    if(!need(q,res,'view','sort','dir')) return
    let rows=[...positions]
    if(q.get('strategy')) rows=rows.filter(r=>r.strategyCode===q.get('strategy'))
    const k=q.get('sort'), dir=q.get('dir')==='asc'?1:-1
    rows.sort((a,b)=>k==='pnl'?((a.pnl??-1e18)-(b.pnl??-1e18))*dir:((Date.parse(a.openedAt||0))-(Date.parse(b.openedAt||0)))*dir)
    for(const a of pendingActions.filter(x=>now<x.at)) { /* noop 占位 */ }
    return J(res,200,rows)
  }
  if (/^\/positions\/[^/]+\/actions$/.test(p)) {
    if(!payload.action) return J(res,400,{error:'action required'})
    const id=p.split('/')[2]
    if(payload.action==='force_close' && id==='LP-FIL') return J(res,409,{error:'FROZEN：冻结态仅允许人工核对后解冻'})
    pendingActions.push({at:Date.now()+800,...payload,id})
    return J(res,202,{accepted:true,note:'结果以 WS position:updates 对账；mock 800ms 后生效'})
  }

  if (p==='/strategies') return J(res,200,strategies)
  if (/^\/strategies\/S[1-6]$/.test(p)) { const s=strategies.find(x=>x.code===p.split('/')[2]); return J(res,200,{...s,rows:positions.filter(r=>r.strategyCode===s.code)}) }
  if (/^\/strategies\/S[1-6]\/toggle$/.test(p)) return J(res,202,{accepted:true})

  if (p==='/rules') { if(!need(q,res,'scope'))return; const s=q.get('scope'); return J(res,200,{scope:s,fields:RULES[s]||RULES._fallback(s),uniqueRow:true}) }
  if (/^\/rules\/.+\/audit$/.test(p)) { const sk=decodeURIComponent(p.split('/')[2]); return J(res,200,RULE_AUDIT.filter(a=>a.scope===sk).concat([{at:'2026-07-12 10:21',user:'admin',scope:sk,field:'E 阈值',change:'10 → 12 bps'}])) }
  if (/^\/rules\//.test(p) && req.method==='PUT') {
    const sk=decodeURIComponent(p.split('/')[2])
    if(Array.isArray(payload.fields)){ RULES[sk]=payload.fields; for(const f of payload.fields) RULE_AUDIT.unshift({at:new Date().toISOString().slice(5,16).replace('T',' '),user:'admin',scope:sk,field:f.label||f.key,change:`→ ${f.value}`}) }
    return J(res,200,{saved:true,hotReloadSec:3,uniqueRow:true})
  }

  if (p==='/accounts' && req.method==='GET') return J(res,200,accounts)
  if (p==='/accounts' && req.method==='POST') { if(!['master','sub'].includes(payload.kind)) return J(res,400,{error:'kind 必选 master|sub'}); return J(res,201,{id:`hustle-new`,...payload}) }
  if (/^\/accounts\/[^/]+\/actions$/.test(p)) return J(res,202,{accepted:true,action:payload.action})

  if (p==='/kms/wallets') return J(res,200,accounts.find(a=>a.platformType==='kms_wallet').children)
  if (p==='/kms/transfers' && req.method==='POST') return J(res,202,{state:'pending_approval',note:'白名单+限额校验通过，等待审批（发起人≠审批人）'})
  if (/^\/kms\/transfers\/[^/]+\/approve$/.test(p)) return J(res,200,{state:'executed',auditId:'sig-000123'})

  if (p==='/monitor/heartbeats') return J(res,200,[{proc:'engine-main',shard:'shard0',age:'2s',ok:true},{proc:'borrow-heartbeat',shard:'global',age:'4s',ok:true}])
  if (p==='/monitor/freshness') return J(res,200,{stale:{count:0,of:200},frozen:{shards:0},divergent:[{symbol:'XAU',score:0.42,state:'observe'}]})
  if (p==='/monitor/balance-watermarks') return J(res,200,[{account:'hustle-004',venue:'OKX',available:'45,210',level:0.18,threshold:'topup',suggestion:{text:'从币安现货划 50,000',feasible:true}},{account:'hustle-006',venue:'MEXC',available:'12,344',level:0.06,threshold:'withdraw',suggestion:{text:'通道维护，暂缓',feasible:false}}])
  if (/^\/monitor\/transfer-suggestions\/.+\/create-order$/.test(p)) return J(res,202,{orderId:'TRF-9001',state:'pending_confirm'})
  if (p==='/monitor/spreads') return J(res,200,spreads)
  if (p==='/monitor/borrowables') return J(res,200,[{symbol:'USDT',qty:'1,234,567.89',usd:'1,234,567.89',health:'正常'},{symbol:'FIL',qty:'—',usd:'—',health:'冻结'}])

  if (p==='/blacklist' && req.method==='GET') return J(res,200,BLACKLIST)
  if (p==='/blacklist' && req.method==='POST') { if(!payload.symbol) return J(res,400,{error:'symbol required'}); BLACKLIST.unshift({symbol:payload.symbol.toUpperCase(),source:'manual',reason:payload.reason||'手动加入',scope:payload.scope||['*'],addedAt:new Date().toISOString().slice(5,16).replace('T',' '),until:payload.until||'永久',hits:0}); return J(res,201,{ok:true}) }
  if (p==='/blacklist/remove' && req.method==='POST') { const i=BLACKLIST.findIndex(b=>b.symbol===payload.symbol); if(i>=0)BLACKLIST.splice(i,1); return J(res,200,{ok:true}) }
  if (p==='/coins') return J(res,200,COINS)
  if (/^\/coins\/[^/]+\/actions$/.test(p)) { const sym=p.split('/')[2]; const c=COINS.find(x=>x.symbol===sym); if(c&&payload.action==='pause')c.state='paused'; if(c&&payload.action==='enable')c.state='enabled'; if(c&&payload.action==='unfreeze'&&c.state==='frozen')return J(res,409,{error:'冻结为风控态：须人工核对裸空后解冻'}); return J(res,202,{accepted:true}) }

  if (p==='/report/pnl') { if(!need(q,res,'range'))return; return J(res,200,pnlDaily) }
  if (p==='/report/attribution') return J(res,200,attribution)
  if (p==='/alerts') return J(res,200,[{at:'12:35:21',level:'FATAL',strategy:'S2',text:'XRPUSDT 距强平 23.1%'},{at:'12:34:57',level:'FATAL',strategy:'S3',text:'USDT 借币失败率 68%'}])
  if (p==='/settings/notifications' && req.method==='GET') return J(res,200,NOTIFY)
  if (p==='/settings/notifications' && req.method==='PUT') { Object.assign(NOTIFY,payload); return J(res,200,{saved:true}) }

  if (p==='/me/earnings/summary') { if(!need(q,res,'view'))return; return J(res,200,{view:q.get('view'),today:2965.27,week:21687.34,total:286720.68}) }
  if (p==='/me/earnings/daily') return J(res,200,pnlDaily)
  if (p==='/me/earnings/sources') return J(res,200,userSources)
  if (p==='/me/subaccounts') { if(!need(q,res,'view'))return; return J(res,200,[{venue:'Binance',asset:102455.32,today:1227.38,total:98765.21},{venue:'OKX',asset:58320.18,today:685.24,total:57320.84}]) }
  if (p==='/me/fund-flows') return J(res,200,[{at:'07-12 11:42',type:'settle',ccy:'USDT',amount:512.34,path:'系统 → Binance·合约',state:'done'}])
  if (p==='/me/ledger' && req.method==='GET') return J(res,200,ledger)
  if (p==='/me/ledger' && req.method==='POST') return J(res,201,{...payload,chainDiffRecalc:true})

  J(res,404,{error:`no mock for ${req.method} ${p}`})
}).listen(PORT,()=>console.log(`[mix-mock] http://localhost:${PORT}/api/v1  (enums: /api/v1/meta/enums)`))
