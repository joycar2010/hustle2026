<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)"
             :title="`规则设置 · ${code} ${nameOf}`" width="980" top="4vh" class="rulemodal">
    <div v-loading="loading">
      <!-- S3：coin 规则模态框 1:1（40 字段五分组 + 自动划转 + 账户资金参数表） -->
      <div v-if="code==='S3'" class="s3form">
        <template v-for="grp in S3_GROUPS" :key="grp.title">
          <div class="ghd">{{ grp.title }}</div>
          <div class="gflex">
            <template v-for="k in grp.keys" :key="k">
              <label v-if="fieldMap[k] && S3_META[k].type==='bool'" class="pill" :class="{on: isTrue(fieldMap[k].value)}"
                     :title="S3_META[k].tip" @click="toggleBool(k)">{{ S3_META[k].label }}</label>
              <span v-else-if="fieldMap[k] && S3_META[k].type==='select'" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <select v-model="fieldMap[k].value" class="sel">
                  <option v-if="!S3_META[k].options.includes(String(fieldMap[k].value))" :value="fieldMap[k].value">{{ fieldMap[k].value }}(当前)</option>
                  <option v-for="o in S3_META[k].options" :key="o" :value="o">{{ o }}</option>
                </select>
              </span>
              <span v-else-if="fieldMap[k] && S3_META[k].type==='venues'" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <span class="venues">
                  <label v-for="v in S3_META[k].options" :key="v" class="vpill"
                         :class="{on: venueOrder(k).includes(v)}" @click="toggleVenue(k, v)">
                    <i v-if="venueOrder(k).includes(v)" class="ord">{{ venueOrder(k).indexOf(v)+1 }}</i>{{ v }}
                  </label>
                </span>
              </span>
              <span v-else-if="fieldMap[k]" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <input v-model="fieldMap[k].value" class="inp" :style="{width:(S3_META[k].w||64)+'px'}" />
                <i v-if="S3_META[k].suffix">{{ S3_META[k].suffix }}</i>
              </span>
            </template>
          </div>
        </template>

        <!-- 自动划转（coin RulesPage 绿框区 1:1） -->
        <div class="ghd">自动划转 / 账户资金</div>
        <div v-if="fundLoading" class="fdim">资金面加载中（coin 实时余额）...</div>
        <template v-else-if="fund">
          <div class="autotransfer">
            <div class="atrow">
              <span class="atlabel">自动划转顺序:</span>
              <select v-model="fundEdit.transfer_order" class="sel atsel">
                <option v-for="o in TRANSFER_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <span class="ifield"><em>主账户保留下限</em>
                <input v-model="fundEdit.base_margin_amount" class="inp" style="width:56px" /><i>U</i></span>
              <i class="fnote">自动补子账户保证金时主账户保底此额,护对冲保证金不被抽干</i>
            </div>
            <div class="atrow" v-if="fund.masterBalance">
              <span class="atlabel dim2">主账户可转</span>
              <span class="mb">全仓 <b>{{ mb('margin_usdt_free') }}</b></span>
              <span class="mb">合约 <b>{{ mb('futures_available') }}</b></span>
              <span class="mb">现货 <b>{{ mb('spot_usdt_free') }}</b></span>
              <i class="fnote">(主账户余额;自动划转对应主账户)</i>
            </div>
          </div>
          <table class="ftable">
            <thead>
              <tr>
                <th class="tl">备注</th><th>BNB</th><th>BNB息</th><th>U借</th><th>保</th><th>可</th><th>可转</th><th>风险</th>
                <th title="保证金水平低于此值即软暂停该子账户下单;覆盖全局">风控阈</th>
                <th title="风险值低于风控阈时每周期从主账户补入该金额;留空=不自动平衡">单笔划</th>
                <th title="子账户保证金保底USDT:低于补足/富余划回">保底额</th>
                <th title="该子账户单笔下单额;优先级 单币规则>子账户>全局">挂单单笔</th>
                <th title="每账户借币金额上限(USDT)">金额限制</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in fund.accounts" :key="a.sub">
                <td class="tl">{{ a.note }}</td>
                <td>{{ fnum(a.balance.bnb_free, 2) }}</td>
                <td>{{ fnum(a.balance.bnb_interest, 4) }}</td>
                <td>{{ fnum(a.balance.margin_usdt_borrowed, 2) }}</td>
                <td>{{ fnum(a.balance.futures_total, 0) }}</td>
                <td>{{ fnum(a.balance.futures_available, 0) }}</td>
                <td>{{ fnum(a.balance.margin_usdt_free, 0) }}</td>
                <td>{{ fnum(a.balance.margin_level, 2) }}</td>
                <td v-for="pk in FUND_PARAM_KEYS" :key="pk">
                  <input v-model="acctEdit[a.sub][pk]" class="inp finp" :class="{mod: isFundMod(a, pk)}" placeholder="—" />
                </td>
                <td><span class="pillbtn" @click="openTransfer(a.sub)">划转</span></td>
              </tr>
              <tr v-if="!fund.accounts.length"><td colspan="14" class="fdim" style="text-align:center">无子账户</td></tr>
            </tbody>
          </table>
          <p class="fnote2">全列已接入 coin 引擎:风控阈(触发自动补保证金/下单暂停)、单笔划(每次从主账户补入额)、保底额(子账户保证金保底)、挂单单笔(覆盖全局下单额)、金额限制(借币封顶)。留空「单笔划」=该子账户不自动平衡。</p>
        </template>
        <div v-else class="fdim">资金面读取失败（coin 桥超时/主账户未配置）——规则字段仍可保存。</div>
      </div>

      <!-- S2：人性化设定 -->
      <div v-else-if="code==='S2'" class="s2form">
        <div class="s2card">
          <div class="s2hd">运行模式 <small>armed=真金下单；切换需输 ARM 二次确认（风控联锁）</small></div>
          <el-radio-group v-model="s2.mode"><el-radio-button value="shadow">影子</el-radio-button><el-radio-button value="armed">武装</el-radio-button></el-radio-group>
        </div>
        <div class="s2card">
          <div class="s2hd">武装方式 <small>advisor=自动信任顾问路由；list=显式白名单</small></div>
          <el-radio-group v-model="s2.arm_mode"><el-radio-button value="advisor">顾问自动</el-radio-button><el-radio-button value="list">显式白名单</el-radio-button></el-radio-group>
          <div class="s2sub"><em>白名单（逗号分隔）</em><el-input v-model="s2.arm_symbols" size="small" style="max-width:420px" /></div>
        </div>
        <div class="s2card">
          <div class="s2hd">仓位限额</div>
          <div class="s2flex">
            <span class="ifield"><em>单币硬顶</em><input v-model="s2.max_notional_hard" class="inp" style="width:70px" /><i>U</i></span>
            <span class="ifield"><em>组合上限</em><input v-model="s2.max_portfolio_notional" class="inp" style="width:70px" /><i>U</i></span>
          </div>
        </div>
      </div>

      <!-- S1/S4：引擎 env 控制,展示当前生效参数(只读) -->
      <div v-else-if="fields.length" class="roform">
        <div class="ronote">{{ code }} 策略参数由引擎 env 控制（不支持网页热改）；以下为当前生效值：</div>
        <div class="rogrid">
          <div v-for="f in fields" :key="f.key" class="rocol"><label>{{ f.label }}</label><b>{{ f.value }}</b></div>
        </div>
      </div>
      <div v-else class="empty">{{ code }} 策略未建 / 无可展示参数。</div>
    </div>
    <template #footer>
      <span class="ver" v-if="version">当前 v{{ version }}</span>
      <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button v-if="code==='S3' || code==='S2'" type="warning" :loading="saving" @click="save">保存设置（热生效）</el-button>
    </template>
  </el-dialog>
  <TransferModal v-model="transfer.open" :accounts="transferAccounts" :default-sub="transfer.sub" @done="loadFund" />
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'
import { S3_META, S3_GROUPS } from './s3meta'
import TransferModal from './TransferModal.vue'

const props = defineProps({ modelValue: Boolean, code: String })
defineEmits(['update:modelValue'])
const NAMES = { S1: '期现收费', S2: '跨所费差', S3: '借币点差', S4: '三率利差', S5: '事件折价', S6: '做量降费' }
const nameOf = computed(() => NAMES[props.code] || '')
const scopeOf = c => ({ S1: 'strategy:S1', S2: 'strategy:S2', S3: 'strategy:S3', S4: 'strategy:S4' }[c])

const TRANSFER_OPTIONS = [
  { value: 'futures,spot,margin', label: '合约 > 现货 > 全仓' },
  { value: 'futures,margin,spot', label: '合约 > 全仓 > 现货' },
  { value: 'spot,futures,margin', label: '现货 > 合约 > 全仓' },
  { value: 'spot,margin,futures', label: '现货 > 全仓 > 合约' },
  { value: 'margin,futures,spot', label: '全仓 > 合约 > 现货' },
  { value: 'margin,spot,futures', label: '全仓 > 现货 > 合约' },
]
const FUND_PARAM_KEYS = ['risk_threshold', 'single_transfer_amount', 'min_balance', 'single_order_amount', 'max_borrow_amount']

const fields = ref([]); const loading = ref(false); const saving = ref(false)
const s2 = ref({ mode: '', arm_mode: '', arm_symbols: '', max_notional_hard: '', max_portfolio_notional: '' })
const fieldMap = computed(() => Object.fromEntries(fields.value.map(f => [f.key, f])))
const version = computed(() => fieldMap.value.version?.value)
const isTrue = v => String(v) === 'True' || String(v) === 'true'
function toggleBool(k) { fieldMap.value[k].value = isTrue(fieldMap.value[k].value) ? 'False' : 'True' }

// venue 有序 pills（borrow_venues：点击加入=排到队尾,再点移除;序号=优先级）
const venueOrder = k => String(fieldMap.value[k]?.value || '').split(',').map(s => s.trim()).filter(Boolean)
function toggleVenue(k, v) {
  const cur = venueOrder(k)
  const next = cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v]
  fieldMap.value[k].value = next.join(',')
}

// ---- S3 资金面（自动划转 + 账户资金参数表） ----
const fund = ref(null); const fundLoading = ref(false)
const fundEdit = reactive({ transfer_order: '', base_margin_amount: '' })
const acctEdit = reactive({})
const transfer = reactive({ open: false, sub: null })
const transferAccounts = computed(() => (fund.value?.accounts || []).map(a => ({ sub: a.sub, note: a.note, balance: a.balance })))
const mb = k => { const v = fund.value?.masterBalance?.[k]; return v == null ? '—' : Math.round(parseFloat(v)) }
const fnum = (v, d) => (v == null ? '—' : parseFloat(v).toFixed(d))
const isFundMod = (a, pk) => String(acctEdit[a.sub]?.[pk] ?? '') !== String(a.params?.[pk] ?? '')
function openTransfer(sub) { transfer.sub = sub; transfer.open = true }

async function loadFund() {
  fundLoading.value = true
  try {
    const f = await mixApi.fundRulesS3()
    fund.value = f
    fundEdit.transfer_order = f.fundRules?.transfer_order || 'futures,spot,margin'
    fundEdit.base_margin_amount = f.fundRules?.base_margin_amount ?? ''
    for (const a of f.accounts) {
      acctEdit[a.sub] = {}
      for (const pk of FUND_PARAM_KEYS) acctEdit[a.sub][pk] = a.params?.[pk] ?? ''
    }
  } catch { fund.value = null }
  finally { fundLoading.value = false }
}

async function load() {
  const scope = scopeOf(props.code)
  if (!scope) { fields.value = []; return }
  loading.value = true
  try {
    const data = await mixApi.rules(scope)
    fields.value = data.fields.map(f => ({ ...f }))
    if (props.code === 'S2') {
      const m = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
      s2.value = { mode: m.mode || '', arm_mode: m.arm_mode || '', arm_symbols: m.arm_symbols || '', max_notional_hard: m.max_notional_hard || '', max_portfolio_notional: m.max_portfolio_notional || '' }
    }
  } finally { loading.value = false }
  if (props.code === 'S3') loadFund()
}
watch(() => props.modelValue, v => { if (v) load() })

async function save() {
  saving.value = true
  try {
    if (props.code === 'S3') {
      const r = await mixApi.rulesSave('strategy:S3', { fields: fields.value })
      if (r.saved) ElMessage.success(`规则已保存 ${r.applied?.length || 0} 项 · ${r.hotReloadSec}s 热生效`)
      else ElMessage.info(r.note || '规则无变更')
      // 资金面差分保存（fund-rules + 逐账户 fund-params）
      if (fund.value) {
        const fr = {}
        if (String(fundEdit.transfer_order) !== String(fund.value.fundRules?.transfer_order ?? '')) fr.transfer_order = fundEdit.transfer_order
        if (String(fundEdit.base_margin_amount) !== String(fund.value.fundRules?.base_margin_amount ?? '')) fr.base_margin_amount = fundEdit.base_margin_amount || null
        const accounts = []
        for (const a of fund.value.accounts) {
          const params = {}
          for (const pk of FUND_PARAM_KEYS) if (isFundMod(a, pk)) params[pk] = acctEdit[a.sub][pk]
          if (Object.keys(params).length) accounts.push({ sub: a.sub, params })
        }
        if (Object.keys(fr).length || accounts.length) {
          const fres = await mixApi.fundRulesS3Save({ fundRules: Object.keys(fr).length ? fr : null, accounts })
          ElMessage.success(`资金面已保存: ${fres.applied?.join('、') || '—'}`)
          loadFund()
        }
      }
    } else if (props.code === 'S2') {
      const orig = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
      const out = []
      for (const k of ['mode', 'arm_mode', 'arm_symbols', 'max_notional_hard', 'max_portfolio_notional']) {
        if (String(s2.value[k]) !== String(orig[k] ?? '')) out.push({ key: k, value: String(s2.value[k]) })
      }
      if (!out.length) { ElMessage.info('无变更'); return }
      const armField = out.find(f => f.key === 'mode' && f.value === 'armed')
      if (armField) {
        const { value } = await ElMessageBox.prompt('切武装=真金下单，输入 ARM 确认', '武装确认', { inputPattern: /^ARM$/, inputErrorMessage: '必须输入 ARM' })
        armField.confirm = value
      }
      const r = await mixApi.rulesSave('strategy:S2', { fields: out })
      if (r.rejected?.length) ElMessage.error('部分被拒: ' + r.rejected.map(x => `${x.key}`).join(','))
      else ElMessage.success(`已保存 ${r.applied?.length || 0} 项`)
    }
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
</script>

<style scoped lang="scss">
.s3form { display: flex; flex-direction: column; gap: 6px; max-height: 74vh; overflow-y: auto; }
.ghd { font-size: 11px; font-weight: 800; color: #F0B90B; letter-spacing: 1px; margin-top: 8px; padding-bottom: 4px; border-bottom: 1px dashed rgba(240,185,11,.25); }
.gflex { display: flex; flex-wrap: wrap; gap: 8px 14px; justify-content: center; padding: 8px 0 4px; }
.ifield { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--el-text-color-secondary); white-space: nowrap;
  em { font-style: normal; } i { font-style: normal; color: var(--el-text-color-placeholder); font-size: 10px; } }
.inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11px; padding: 3px 6px; text-align: right;
  &:focus { outline: none; border-color: #F0B90B; } }
.sel { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11px; padding: 3px 4px; &:focus { outline: none; border-color: #F0B90B; } }
.pill { display: inline-flex; align-items: center; border: 1px solid var(--el-border-color); border-radius: 20px; padding: 3px 12px; font-size: 11px; color: var(--el-text-color-secondary); cursor: pointer; user-select: none;
  &.on { background: rgba(240,185,11,.16); border-color: #F0B90B; color: #F0B90B; font-weight: 700; } }
.venues { display: inline-flex; gap: 4px; }
.vpill { display: inline-flex; align-items: center; gap: 3px; border: 1px solid var(--el-border-color); border-radius: 10px; padding: 2px 8px; font-size: 10px; color: var(--el-text-color-secondary); cursor: pointer; user-select: none;
  .ord { font-style: normal; background: #F0B90B; color: #12151A; border-radius: 50%; width: 12px; height: 12px; line-height: 12px; text-align: center; font-size: 8.5px; font-weight: 800; }
  &.on { border-color: #F0B90B; color: #F0B90B; } }
// ---- 资金面 ----
.autotransfer { border: 1px solid rgba(14,203,129,.45); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.atrow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 11px; }
.atlabel { color: #0ECB81; font-weight: 700; }
.dim2 { color: rgba(14,203,129,.7); font-weight: 400; font-size: 10px; }
.atsel { min-width: 150px; }
.mb { color: var(--el-text-color-secondary); b { color: #EAECEF; font-family: monospace; margin-left: 3px; } }
.fnote { font-style: normal; font-size: 9.5px; color: var(--el-text-color-placeholder); }
.fnote2 { font-size: 9.5px; color: var(--el-text-color-placeholder); margin: 2px 4px; }
.fdim { font-size: 11px; color: var(--el-text-color-placeholder); padding: 10px; }
.ftable { border-collapse: collapse; width: 100%; font-size: 10.5px; margin-top: 6px;
  th { background: #0d0d14; color: var(--el-text-color-secondary); padding: 5px 4px; font-weight: 600; white-space: nowrap; border-bottom: 1px solid var(--el-border-color); text-align: right; }
  td { padding: 3px 4px; text-align: right; border-bottom: 1px solid rgba(255,255,255,.05); font-family: monospace; white-space: nowrap; }
  .tl { text-align: left; font-family: inherit; } }
.finp { width: 52px; &.mod { color: #f59e0b; border-color: rgba(245,158,11,.55); background: rgba(245,158,11,.08); } }
.pillbtn { display: inline-block; border: 1px solid rgba(240,185,11,.4); background: rgba(240,185,11,.12); color: #F0B90B; border-radius: 5px; padding: 1px 8px; font-size: 10px; cursor: pointer; font-family: inherit;
  &:hover { background: rgba(240,185,11,.25); } }
.s2form { display: flex; flex-direction: column; gap: 12px; max-width: 640px; margin: 0 auto; }
.s2card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.s2hd { font-size: 12.5px; font-weight: 700; margin-bottom: 10px; small { color: var(--el-text-color-placeholder); font-weight: 400; margin-left: 8px; } }
.s2sub { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; em { font-style: normal; font-size: 11px; color: var(--el-text-color-secondary); } }
.s2flex { display: flex; gap: 18px; flex-wrap: wrap; }
.roform { padding: 4px; }
.ronote { font-size: 11.5px; color: var(--el-text-color-secondary); margin-bottom: 12px; }
.rogrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.rocol { display: flex; flex-direction: column; gap: 3px; border: 1px solid var(--el-border-color); border-radius: 8px; padding: 8px 10px;
  label { font-size: 11px; color: var(--el-text-color-placeholder); } b { font-size: 13px; color: var(--el-text-color-primary); } }
.empty { color: var(--el-text-color-secondary); font-size: 12px; padding: 30px; text-align: center; }
.ver { margin-right: auto; font-size: 11px; color: var(--el-text-color-placeholder); }
</style>
