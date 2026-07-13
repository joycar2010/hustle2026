<template>
  <!-- S3 通用规则面板（coin 规则模态框 1:1:40 字段五分组 + 自动划转 + 账户资金参数表）
       共享组件:中控台 RuleSettingsModal 与 规则中心 MixRules 同源复用——改这里两处生效。
       保存按钮在宿主(弹层 footer / 页面 acts),经 defineExpose 调 load()/save()。 -->
  <div class="s3form" v-loading="loading">
    <div class="verline" v-if="version"><span class="ver">当前 v{{ version }}</span></div>
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
  <TransferModal v-model="transfer.open" :accounts="transferAccounts" :default-sub="transfer.sub" @done="loadFund" />
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'
import { S3_META, S3_GROUPS } from './s3meta'
import TransferModal from './TransferModal.vue'

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

// ---- 资金面（自动划转 + 账户资金参数表） ----
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
  loading.value = true
  try {
    const data = await mixApi.rules('strategy:S3')
    fields.value = data.fields.map(f => ({ ...f }))
  } finally { loading.value = false }
  loadFund()
}

async function save() {
  saving.value = true
  try {
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
    load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}

onMounted(load)
defineExpose({ load, save, saving, loading })
</script>

<style scoped lang="scss">
.s3form { display: flex; flex-direction: column; gap: 6px; max-height: 74vh; overflow-y: auto; }
.verline { display: flex; justify-content: flex-end; .ver { font-size: 10.5px; color: var(--el-text-color-placeholder); } }
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
</style>
