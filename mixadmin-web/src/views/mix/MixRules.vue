<template>
  <div class="mixrules">
    <!-- 左：作用域树（通知设置已迁通知模块;审计已迁屏3风控墙） -->
    <div class="scopes">
      <div class="grp">策略模板</div>
      <div v-for="s in strategyList" :key="s.code" class="item"
           :class="{on:scope===`strategy:${s.code}`}"
           :style="scope===`strategy:${s.code}`?{background:META[s.code].colorBg,color:META[s.code].color}:{}"
           @click="setScope(`strategy:${s.code}`)">
        {{ s.code }} · {{ s.name }}
      </div>
      <div class="note">保存=差分写(只发变更键)·热生效引擎回读校验；变更审计移驻 屏3·风控墙</div>
    </div>

    <!-- 中：设定台（S3=coin 规则模态框 1:1 复刻;S2=人性化开关;整体居中收窄） -->
    <div class="stage">
      <div class="crumb">
        <b>{{ scopeLabel }}</b>
        <el-tag v-if="scope==='strategy:S3'" size="small" type="warning" effect="plain">coin 权威 · 30s 热重载</el-tag>
        <el-tag v-else-if="scope==='strategy:S2'" size="small" type="warning" effect="plain">gateway 权威 · 3s 热生效</el-tag>
        <span class="ver" v-if="version">v{{ version }}</span>
      </div>

      <!-- S3：分组 inline 字段,flex 自动折行,绝不产生空单元格 -->
      <div v-if="scope==='strategy:S3'" class="s3form" v-loading="loading">
        <template v-for="grp in S3_GROUPS" :key="grp.title">
          <div class="ghd">{{ grp.title }}</div>
          <div class="gflex">
            <template v-for="k in grp.keys" :key="k">
              <label v-if="fieldMap[k] && S3_META[k].type==='bool'" class="pill" :class="{on: isTrue(fieldMap[k].value)}"
                     :title="S3_META[k].tip" @click="toggleBool(k)">{{ S3_META[k].label }}</label>
              <span v-else-if="fieldMap[k] && S3_META[k].type==='select'" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <select v-model="fieldMap[k].value" class="sel">
                  <option v-for="o in S3_META[k].options" :key="o" :value="o">{{ o }}</option>
                </select>
              </span>
              <span v-else-if="fieldMap[k]" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <input v-model="fieldMap[k].value" class="inp" :style="{width:(S3_META[k].w||64)+'px'}" />
                <i v-if="S3_META[k].suffix">{{ S3_META[k].suffix }}</i>
              </span>
            </template>
          </div>
        </template>
        <div class="acts">
          <el-button type="warning" :loading="saving" @click="save">保存设置（差分热生效）</el-button>
          <el-button @click="load">还原</el-button>
        </div>
      </div>

      <!-- S2：去参数化,人性化设定 -->
      <div v-else-if="scope==='strategy:S2'" class="s2form" v-loading="loading">
        <div class="s2card">
          <div class="s2hd">运行模式 <small>armed=真金下单;切换需二次确认,联锁要求风控全绿</small></div>
          <el-radio-group v-model="s2.mode" size="large">
            <el-radio-button value="shadow">shadow · 只决策不下单</el-radio-button>
            <el-radio-button value="armed">armed · 真金执行</el-radio-button>
          </el-radio-group>
        </div>
        <div class="s2card">
          <div class="s2hd">武装方式 <small>advisor=自动信任顾问名下 active 路由;list=仅显式白名单</small></div>
          <el-radio-group v-model="s2.arm_mode">
            <el-radio-button value="advisor">advisor · 顾问自动</el-radio-button>
            <el-radio-button value="list">list · 显式白名单</el-radio-button>
          </el-radio-group>
          <div class="s2sub">
            <em>白名单（逗号分隔,list 模式生效;人工路由任何模式须列名）</em>
            <el-input v-model="s2.arm_symbols" size="small" placeholder="如 AMATUSDT,PARTIUSDT" style="max-width:420px" />
          </div>
        </div>
        <div class="s2card">
          <div class="s2hd">仓位限额</div>
          <div class="s2flex">
            <span class="ifield"><em>单币硬顶</em><input v-model="s2.max_notional_hard" class="inp" style="width:70px" /><i>U</i></span>
            <span class="ifield"><em>组合上限</em><input v-model="s2.max_portfolio_notional" class="inp" style="width:70px" /><i>U</i></span>
          </div>
        </div>
        <div class="acts">
          <el-button type="warning" :loading="saving" @click="saveS2">保存设置（写代理 · gateway 审计）</el-button>
          <el-button @click="load">还原</el-button>
        </div>
      </div>

      <!-- 其余作用域：引擎侧尚无权威读写点,如实标注 -->
      <div v-else class="empty">
        该作用域（{{ scopeLabel }}）引擎侧尚无权威配置读写点——不渲染假模板（防「UI 写了引擎不读」病）。
        S1 期现引擎参数随 armed 专场接入。
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const strategyList = Object.values(META)
const scope = ref('strategy:S3')
const fields = ref([])
const loading = ref(false)
const saving = ref(false)
const s2 = ref({ mode: '', arm_mode: '', arm_symbols: '', max_notional_hard: '', max_portfolio_notional: '' })

/* S3 字段元数据 —— 1:1 对齐 coin 规则模态框的中文语汇/分组(coin RulesPage/SymbolRuleDialog 同源) */
const S3_META = {
  auto_push_spread: { label: '自动推送点差', w: 56, tip: '点差≥此值自动推送进候选' },
  confirm_delay_sec: { label: '推送二次确认', suffix: '秒', w: 40 },
  confirm_skip_spread: { label: '点差≥直推(免确认)', w: 56 },
  interest_filter: { label: '日利息拦截', suffix: '%', w: 48, tip: '日利率高于此值的币不进候选' },
  remove_spread: { label: '点差不足移除', w: 56 },
  removed_cooldown_minutes: { label: '移除后冷却', suffix: '分', w: 40 },
  spread_stale_sec: { label: '点差过期', suffix: '秒', w: 48 },
  borrow_spread: { label: '挂单点差', w: 56 },
  open_spread: { label: '开仓点差', w: 56 },
  open_spread_buffer: { label: '开仓点差缓冲', w: 56 },
  order_amount: { label: '单笔下单额', suffix: 'U', w: 56 },
  borrow_delay_sec: { label: '借币延迟开仓', suffix: '秒', w: 40 },
  stabilize_sec: { label: '点差稳定期', suffix: '秒', w: 48 },
  slippage_pct: { label: '滑点保护', suffix: '%', w: 48 },
  follow_type: { label: '跟单方式', type: 'select', options: ['market', 'limit'] },
  tier_ratios: { label: '阶梯比例', w: 90, tip: '逗号分隔;空=不分层' },
  max_spread_pct: { label: '最大点差', suffix: '%', w: 48 },
  min_volume_24h: { label: '24h最小成交额·现货', w: 72 },
  min_volume_24h_futures: { label: '24h最小成交额·合约', w: 72 },
  filter_duration_ms: { label: '过滤持续', suffix: 'ms', w: 48 },
  min_borrow_usdt: { label: '最小借币额', suffix: 'U', w: 56 },
  block_risky_open: { label: '风险开仓拦截', type: 'bool' },
  close_spread: { label: '平仓点差', w: 56 },
  close_funding_ratio: { label: '平仓:资息倍率<', w: 48 },
  repay_funding_ratio: { label: '还币:资息倍率<', w: 48 },
  repay_ban_minutes: { label: '首借后禁自动还币', suffix: '分', w: 40 },
  borrow_rate_per_sec: { label: '借币速率', suffix: '/秒', w: 40 },
  borrow_via_otoco: { label: 'OTOCO 借币', type: 'bool', tip: 'OTOCO=1500 权重独立预算' },
  otoco_legs: { label: 'OTOCO 腿数', w: 32 },
  borrow_mode: { label: '借币方式', w: 72, tip: '4 模式;None=默认' },
  borrow_venues: { label: '借币 venue', w: 100, tip: '逗号分隔,如 binance,okx' },
  multi_max_accounts_per_symbol: { label: '单币最多账户', w: 32 },
  collateral_ratio: { label: '质押率', w: 48 },
  hedge_via_master: { label: '主账户对冲', type: 'bool', tip: 'hedge_via_master:合约对冲腿走主账户' },
  hedge_auto_converge: { label: '对冲自动收敛', type: 'bool' },
  max_loss_per_position: { label: '单仓最大亏损', suffix: 'U', w: 56, tip: 'None=不启用' },
  taker_fee_spot: { label: '现货 taker 费率', w: 72 },
  taker_fee_futures: { label: '合约 taker 费率', w: 72 },
  bnb_burn_enabled: { label: 'BNB 抵扣手续费', type: 'bool' },
}
const S3_GROUPS = [
  { title: '推送 / 候选', keys: ['auto_push_spread', 'confirm_delay_sec', 'confirm_skip_spread', 'interest_filter', 'remove_spread', 'removed_cooldown_minutes', 'spread_stale_sec'] },
  { title: '开仓', keys: ['borrow_spread', 'open_spread', 'open_spread_buffer', 'order_amount', 'borrow_delay_sec', 'stabilize_sec', 'slippage_pct', 'follow_type', 'tier_ratios', 'max_spread_pct', 'min_volume_24h', 'min_volume_24h_futures', 'filter_duration_ms', 'min_borrow_usdt', 'block_risky_open'] },
  { title: '平仓 / 还币', keys: ['close_spread', 'close_funding_ratio', 'repay_funding_ratio', 'repay_ban_minutes'] },
  { title: '借币执行', keys: ['borrow_rate_per_sec', 'borrow_via_otoco', 'otoco_legs', 'borrow_mode', 'borrow_venues', 'multi_max_accounts_per_symbol', 'collateral_ratio'] },
  { title: '对冲 / 风控 / 费率', keys: ['hedge_via_master', 'hedge_auto_converge', 'max_loss_per_position', 'taker_fee_spot', 'taker_fee_futures', 'bnb_burn_enabled'] },
]

const fieldMap = computed(() => Object.fromEntries(fields.value.map(f => [f.key, f])))
const version = computed(() => fieldMap.value.version?.value)
const isTrue = v => String(v) === 'True' || String(v) === 'true'
function toggleBool(k) { fieldMap.value[k].value = isTrue(fieldMap.value[k].value) ? 'False' : 'True' }

const scopeLabel = computed(() => {
  const [, v] = scope.value.split(':')
  return `${v} · ${META[v]?.name || ''} 模板`
})

async function load() {
  loading.value = true
  try {
    const data = await mixApi.rules(scope.value)
    fields.value = data.fields.map(f => ({ ...f }))
    if (scope.value === 'strategy:S2') {
      const m = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
      s2.value = { mode: m.mode || '', arm_mode: m.arm_mode || '', arm_symbols: m.arm_symbols || '',
                   max_notional_hard: m.max_notional_hard || '', max_portfolio_notional: m.max_portfolio_notional || '' }
    }
  } finally { loading.value = false }
}
function setScope(s) { scope.value = s; load() }

async function save() {
  saving.value = true
  try {
    const r = await mixApi.rulesSave(scope.value, { fields: fields.value })
    if (r.saved) ElMessage.success(`已保存 ${r.applied?.length || 0} 项 · ${r.hotReloadSec}s 热生效`)
    else ElMessage.info(r.note || '无变更')
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
async function saveS2() {
  const orig = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
  const out = []
  for (const k of ['mode', 'arm_mode', 'arm_symbols', 'max_notional_hard', 'max_portfolio_notional']) {
    if (String(s2.value[k]) !== String(orig[k] ?? '')) out.push({ key: k, value: String(s2.value[k]) })
  }
  if (!out.length) return ElMessage.info('无变更')
  // armed 联锁：切 armed 须显式打 ARM（gateway confirm=ARM 二次确认原样透传）
  const modeField = out.find(f => f.key === 'mode' && f.value === 'armed')
  if (modeField) {
    try {
      const { value } = await ElMessageBox.prompt('切换 armed=真金下单。输入 ARM 确认（gateway 联锁要求风控全绿）', '武装确认', { inputPattern: /^ARM$/, inputErrorMessage: '必须输入 ARM' })
      modeField.confirm = value
    } catch { return }
  }
  saving.value = true
  try {
    const r = await mixApi.rulesSave('strategy:S2', { fields: out })
    if (r.rejected?.length) ElMessage.error(`部分被拒: ${r.rejected.map(x => `${x.key}(${x.error})`).join('; ')}`)
    else ElMessage.success(`已保存 ${r.applied?.length || 0} 项 · 引擎 ${r.hotReloadSec}s 回读生效`)
    load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
onMounted(load)
</script>

<style scoped lang="scss">
.mixrules { display: grid; grid-template-columns: 200px 1fr; gap: 12px; align-items: start; }
.scopes { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 8px; display: flex; flex-direction: column; gap: 2px;
  .grp { font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px 2px; font-weight: 700; }
  .item { padding: 7px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; color: var(--el-text-color-regular);
    &:hover { background: var(--el-fill-color-light); }
    &.on { background: rgba(240,185,11,.14); color: #B8860B; font-weight: 700; } }
  .note { margin-top: 8px; font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px; border-top: 1px dashed var(--el-border-color); } }

/* 设定台整体收窄居中 */
.stage { max-width: 920px; margin: 0 auto; width: 100%; border: 1px solid var(--el-border-color); border-radius: 10px; padding: 14px 20px; background: var(--mix-card, #181B21); }
.crumb { display: flex; align-items: center; gap: 10px; font-size: 13px; margin-bottom: 12px;
  b { font-weight: 800; } .ver { margin-left: auto; color: var(--el-text-color-placeholder); font-size: 11px; } }

/* S3：coin 模态框同款——分组标题+行内小字段,flex 折行,无空单元格,组内容居中 */
.s3form { display: flex; flex-direction: column; gap: 6px; }
.ghd { font-size: 11px; font-weight: 800; color: #F0B90B; letter-spacing: 1px; margin-top: 8px;
  padding-bottom: 4px; border-bottom: 1px dashed rgba(240,185,11,.25); }
.gflex { display: flex; flex-wrap: wrap; gap: 8px 14px; justify-content: center; padding: 8px 0 4px; }
.ifield { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--el-text-color-secondary); white-space: nowrap;
  em { font-style: normal; } i { font-style: normal; color: var(--el-text-color-placeholder); font-size: 10px; } }
.inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF;
  font-size: 11px; padding: 3px 6px; text-align: right;
  &:focus { outline: none; border-color: #F0B90B; } }
.sel { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11px; padding: 3px 4px;
  &:focus { outline: none; border-color: #F0B90B; } }
.pill { display: inline-flex; align-items: center; border: 1px solid var(--el-border-color); border-radius: 20px;
  padding: 3px 12px; font-size: 11px; color: var(--el-text-color-secondary); cursor: pointer; user-select: none;
  &.on { background: rgba(240,185,11,.16); border-color: #F0B90B; color: #F0B90B; font-weight: 700; } }
.acts { margin-top: 16px; display: flex; gap: 8px; justify-content: center; }

/* S2：人性化卡片 */
.s2form { display: flex; flex-direction: column; gap: 12px; max-width: 640px; margin: 0 auto; }
.s2card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.s2hd { font-size: 12.5px; font-weight: 700; margin-bottom: 10px;
  small { color: var(--el-text-color-placeholder); font-weight: 400; margin-left: 8px; } }
.s2sub { margin-top: 10px; display: flex; flex-direction: column; gap: 6px;
  em { font-style: normal; font-size: 11px; color: var(--el-text-color-secondary); } }
.s2flex { display: flex; gap: 18px; flex-wrap: wrap; }
.empty { color: var(--el-text-color-secondary); font-size: 12px; padding: 30px 10px; text-align: center; }
</style>
