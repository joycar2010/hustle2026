<template>
  <div class="aicoin">
    <RiskStatusBar />
    <!-- 研判对象条:canonical 搜索(§7.1)——币种/交易对/中英文别名;AiCoin dbKey 只在服务端 -->
    <div class="objbar card">
      <b class="sym" @click="openAsset360(sym)" style="cursor:pointer" title="点击查看Asset 360">{{ sym || '—' }}</b>
      <el-select v-model="prod" size="small" style="width:88px" title="研判目标产品(决定指标面与计划产品)" @change="loadAll">
        <el-option v-for="p in PRODUCTS" :key="p" :value="p"/>
      </el-select>
      <el-autocomplete v-model="kw" :fetch-suggestions="suggest" placeholder="搜索 BTC、BTCUSDT、Bitcoin"
        size="small" style="width:300px" clearable @select="onPick">
        <template #default="{ item }">
          <div class="sug">
            <b>{{ item.displayName }}</b>
            <span class="sgm">{{ (item.markets||[]).join('/') }} · {{ (item.venues||[]).length }}所</span>
            <span class="sgp">{{ (item.availableProducts||[]).join(' ') }}</span>
            <span class="sga" :class="{ok:item.aicoinAvailable===true}">{{ item.aicoinAvailable===true ? 'AiCoin·可用' : item.aicoinAvailable===false ? '无图' : '' }}</span>
          </div>
        </template>
      </el-autocomplete>
      <i class="tag" v-if="recent.length">最近:
        <a v-for="r in recent" :key="r" class="rc" @click="pickSym(r)">{{ r.replace('USDT','') }}</a></i>
      <span class="dimtxt">数据时间 {{ dataTs || (ctx?.as_of||'').slice(11,19)+' UTC' }}</span>
      <span class="grow" />
      <el-button size="small" type="warning" plain @click="openAiCoinSite">打开 AiCoin ↗</el-button>
      <el-button size="small" @click="copySym">复制交易对</el-button>
      <el-radio-group v-model="period" size="small" @change="loadK">
        <el-radio-button v-for="p in PERIODS" :key="p.v" :value="p.v">{{ p.t }}</el-radio-button>
      </el-radio-group>
      <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
    </div>
    <!-- 冲突提示黄条:AiCoin vs 官方,无"采用AiCoin数据"选项 -->
    <div class="conflict" v-if="conflict">
      <span class="ct"><FIcon name="warn" :size="12"/> 外部参考与官方数据存在差异</span>
      <span class="dimtxt">AiCoin 观察价 {{ conflict.ai }} ｜ 官方可成交价 {{ conflict.official }} ｜ 差异 {{ conflict.pct }}% — 外部参考不可覆盖正式数据</span>
      <span class="grow" />
      <el-button size="small" @click="scrollVenues">查看各所报价</el-button>
      <el-button size="small" @click="markAnomaly">标记数据异常</el-button>
    </div>

    <!-- 主体三栏:左官方事实行 | 中AiCoin观察 | 右人工研判(快速四步/完整) -->
    <div class="tri">
      <div class="card lcol" ref="venuesEl">
        <div class="chd2"><b>系统官方快照</b><span class="dimtxt">开仓硬闸唯一数据源 · 每行可悬停看来源与原因</span></div>
        <!-- §7.2 数据事实行:MetricValueEnvelope 渲染,无裸 N/A -->
        <div class="facts">
          <div v-for="f in FACTS" :key="f.k" class="frow">
            <span class="fl">{{ f.t }}</span>
            <ValueCell :value="mval(f.k)" :state="mstate(f.k)" :suffix="f.sfx" :dp="f.dp" :reason="mreason(f.k)"/>
            <span class="fsrc">{{ msrc(f.k) }}</span>
          </div>
        </div>
        <div class="vhead"><span>Venue</span><span>模式</span><span class="r">中价</span><span class="r">点差</span><span class="r">费%/d</span><span>鲜</span></div>
        <div v-for="r in va" :key="r.venue" class="vrow" :class="{stale: !r.fresh}">
          <span><b>{{ r.venue }}</b></span><span :class="'m-'+r.mode">{{ r.mode }}</span>
          <span class="r">{{ r.mid ?? '—' }}</span><span class="r">{{ r.spread_bps ?? '—' }}</span>
          <span class="r">{{ r.funding_daily_pct ?? '—' }}</span><span><FIcon :name="r.fresh?'check':'x'" :size="11"/></span>
        </div>
      </div>

      <div class="card mcol">
        <div class="chd2"><b>AiCoin 观察区</b><span class="dimtxt">人工参考 · 不进入自动交易链路</span><span class="grow" /><span class="dimtxt">{{ note }}</span></div>
        <div v-show="aiOk" ref="chartEl" class="kchart"></div>
        <div v-if="!aiOk" class="aimiss">
          <b>官方行情可用,AiCoin 图表尚未匹配</b>
          <p>{{ ctx?.aicoin?.reason === 'AICOIN_NOT_CONFIGURED' ? 'AiCoin 未配置(系统配置→AiCoin)' : '该币种在 AiCoin 无对应图表映射——不影响研判与官方数据' }}</p>
        </div>
      </div>

      <div class="card rcol">
        <div class="chd2"><b>人工研判</b>
          <el-radio-group v-model="noteMode" size="small" style="margin-left:8px">
            <el-radio-button value="quick">快速研判</el-radio-button>
            <el-radio-button value="full">完整审查</el-radio-button>
          </el-radio-group>
          <span class="dimtxt">{{ noteMode==='quick' ? '四步·30秒·只追加' : 'C2.P 正式准备 · 全必填' }}</span>
        </div>
        <!-- §7.3 快速研判:四步选项化,不暴露内部字段 -->
        <div v-if="noteMode==='quick'" class="quick">
          <div class="qsec"><i>① 当前阶段</i>
            <div class="chips"><span v-for="o in Q_STAGE" :key="o" class="chip" :class="{on:quick.stage===o}" @click="quick.stage=o">{{ o }}</span></div></div>
          <div class="qsec"><i>② 主要依据(多选)</i>
            <div class="chips"><span v-for="o in Q_BASIS" :key="o" class="chip" :class="{on:quick.basis.includes(o)}" @click="tgl(quick.basis,o)">{{ o }}</span></div></div>
          <div class="qsec"><i>③ 主要风险(多选)</i>
            <div class="chips"><span v-for="o in Q_RISK" :key="o" class="chip warn" :class="{on:quick.risks.includes(o)}" @click="tgl(quick.risks,o)">{{ o }}</span></div></div>
          <div class="qsec"><i>④ 补充一句话(可选)</i>
            <el-input v-model="quick.note" size="small" placeholder="如:盯 8h 结算前费差变化"/></div>
          <div class="qbtns">
            <el-button size="small" :loading="saving==='OBSERVE'" @click="saveQuick('OBSERVE')">继续观察</el-button>
            <el-button size="small" type="danger" plain :loading="saving==='REJECT'" @click="saveQuick('REJECT')">暂不参与</el-button>
            <el-button size="small" type="primary" :loading="saving==='PREPARE_PLAN'" @click="saveQuick('PREPARE_PLAN')">完成研判并生成计划</el-button>
          </div>
          <p class="qnote">研判只产结论,本页无直接开仓;计划走 DRY_RUN→冷却→二次认证</p>
        </div>
        <!-- §7.4 完整审查:C2.P 正式准备 -->
        <el-form v-else label-width="96px" size="small" class="labform">
          <el-form-item label="市场阶段"><el-select v-model="full.market_stage" placeholder="必选">
            <el-option v-for="o in Q_STAGE" :key="o" :value="o" /></el-select></el-form-item>
          <el-form-item label="置信度"><el-select v-model="full.confidence_level" placeholder="仅人工标签,非系统事实">
            <el-option v-for="o in ['高(人工)','中(人工)','低(人工)']" :key="o" :value="o" /></el-select></el-form-item>
          <el-form-item label="支持证据"><el-input v-model="full.efor" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="反对证据"><el-input v-model="full.eagainst" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="失效条件"><el-input v-model="full.thesis_invalidation" placeholder="如:费差<6bps 连2期" /></el-form-item>
          <el-form-item label="最晚复核"><el-date-picker v-model="full.review_at" type="datetime" style="width:100%" placeholder="到点未复核=研判过期"/></el-form-item>
          <el-form-item label="建议路线"><el-input v-model="full.recommended_route" placeholder="如 bitget(空)↔binance(多),可留空由预览建议" /></el-form-item>
          <el-form-item label="建议金额U"><el-input-number v-model="full.recommended_notional" :min="0" style="width:100%" /></el-form-item>
          <el-form-item label="最长持有"><el-input v-model="full.max_holding_time" placeholder="如 72h" /></el-form-item>
          <el-form-item label="结论"><el-radio-group v-model="full.decision">
            <el-radio value="OBSERVE">观察</el-radio><el-radio value="PREPARE_PLAN">准备计划</el-radio><el-radio value="REJECT">不参与</el-radio>
          </el-radio-group></el-form-item>
          <div class="qbtns">
            <el-button size="small" :loading="saving==='FULL'" type="primary" @click="saveFull">完成研判{{ full.decision==='PREPARE_PLAN' ? '并生成计划' : '' }}</el-button>
          </div>
        </el-form>
      </div>
    </div>

    <!-- 研判案件历史(新表+旧案件只读映射) -->
    <div class="card hist">
      <div class="chd2"><b>研判案件 · {{ cases.length }}</b><span class="dimtxt">只追加不覆盖 · 用于验证人工判断的预测价值</span></div>
      <div class="hhead"><span>时间</span><span>操作员</span><span>币</span><span>阶段</span><span>结论</span><span>模式</span><span>摘要</span></div>
      <div v-if="!cases.length" class="dimtxt pad">无历史案件</div>
      <div v-for="c in cases" :key="c.id" class="hrow">
        <span>{{ (c.created_at||'').slice(5,16) }}</span><span>{{ c.created_by }}</span>
        <span><b>{{ (c.canonical_symbol||'').replace('USDT','') }}</b><i v-if="c.source==='legacy'" class="lg">旧</i></span>
        <span>{{ c.market_stage || '—' }}</span>
        <span :class="c.decision==='REJECT' ? 'bad' : c.decision==='PREPARE_PLAN' ? 'gold' : ''">{{ DEC_CN[c.decision] || c.decision }}</span>
        <span>{{ c.review_mode==='FULL' ? '完整' : '快速' }}</span>
        <span class="dimtxt ell" :title="c.summary_text">{{ c.summary_text }}</span>
      </div>
    </div>

    <!-- 决策条:系统计算数字 + 无直接开仓 -->
    <div class="card decide">
      <div class="nums">
        <div class="num"><span>候选E(风调)</span><b><ValueCell :value="mval('candidate_ev_bps')" :state="mstate('candidate_ev_bps')" suffix=" bps" :dp="1"/></b></div>
        <div class="num"><span>跨所费差</span><b><ValueCell :value="mval('funding_gap_daily_pct')" :state="mstate('funding_gap_daily_pct')" suffix=" %/日" :dp="4"/></b></div>
      </div>
      <span class="dimtxt flow">无「直接开仓」:研判 → 人工计划 → 冷却 → 二次认证 → shadow 终态 → SOP 放行执行</span>
    </div>

    <!-- 人工计划弹窗(§5):预览全 envelope;生成=dry_run_proposal 既有审批链 -->
    <el-dialog v-model="planDlg.open" :title="`生成 ${prod} 人工计划（DRY_RUN 先行 · 不下单）`" width="560px">
      <div class="pgrid">
        <el-form label-width="90px" size="small">
          <el-form-item label="标的"><b>{{ sym }}</b><i class="tag" style="margin-left:8px">研判 #{{ planDlg.caseId }}</i></el-form-item>
          <el-form-item label="目标名义U"><el-input-number v-model="planDlg.notional" :min="0" style="width:100%" @change="loadPreview"/></el-form-item>
          <el-form-item label="多腿venue"><el-input v-model="planDlg.venue_long" size="small" @change="loadPreview"/></el-form-item>
          <el-form-item label="空腿venue"><el-input v-model="planDlg.venue_short" size="small" @change="loadPreview"/></el-form-item>
        </el-form>
        <div class="pv">
          <div class="pvh">计划预览 <span class="dimtxt">{{ planDlg.preview?.route?.source || '' }}</span></div>
          <div v-for="p in PREVIEW_ROWS" :key="p.k" class="frow">
            <span class="fl">{{ p.t }}</span>
            <ValueCell :value="planDlg.preview?.preview?.[p.k]?.value" :state="planDlg.preview?.preview?.[p.k]?.state"
                       :suffix="p.sfx" :dp="p.dp" :reason="planDlg.preview?.preview?.[p.k]?.reason||''"/>
          </div>
          <div class="frow"><span class="fl">研判失效条件</span><span class="inval">{{ planDlg.preview?.thesis_invalidation || '—' }}</span></div>
        </div>
      </div>
      <p class="qnote">{{ planDlg.preview?.risk_note }}</p>
      <template #footer>
        <el-button @click="planDlg.open=false">取消</el-button>
        <el-button type="primary" :loading="planDlg.busy" :disabled="!planDlg.notional" @click="createPlan">生成 DRY_RUN 提案</el-button>
      </template>
    </el-dialog>
  </div>
  <!-- Asset 360 抽屉 -->
  <Asset360 v-model:open="a360Open" :symbol="a360Symbol" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import Asset360 from '../../components/v62/Asset360.vue'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import ValueCell from '../../components/v62/ValueCell.vue'
import { mixApi } from '../../api/mix'

const route = useRoute(); const router = useRouter()
const PERIODS = [{ v: '15', t: '15m' }, { v: '60', t: '1h' }, { v: '240', t: '4h' }, { v: '1440', t: '1D' }]
const DEC_CN = { OBSERVE: '继续观察', PREPARE_PLAN: '准备计划', REJECT: '不参与' }
const Q_STAGE = ['蓄力', '拉升中', '高位震荡', '开始转弱', '看不清']
const Q_BASIS = ['费差扩大', 'OI增加', '成交放大', '多平台同步', '资金费接近上限', '反复拉升砸盘']
const Q_RISK = ['突然砸盘', '费差收窄', '单平台异常', '深度不足', '资金费反转']
const FACTS = [
  { k: 'price', t: '现价(最优中价)', sfx: '', dp: 6 },
  { k: 'spread_min_bps', t: '最窄点差', sfx: ' bps', dp: 2 },
  { k: 'vol24h_usdt', t: '全市场24h成交量', sfx: ' USDT', dp: 0 },
  { k: 'oi_usdt', t: '全市场合约持仓', sfx: ' USDT', dp: 0 },
  { k: 'depth_buy_25bps', t: '25bps买入深度', sfx: ' USDT', dp: 0 },
  { k: 'depth_sell_25bps', t: '25bps卖出深度', sfx: ' USDT', dp: 0 },
  { k: 'funding_gap_daily_pct', t: '跨所费差', sfx: ' %/日', dp: 4 },
  { k: 'funding_coverage', t: '资金费覆盖平台', sfx: '/6', dp: 0 },
  { k: 'funding_interval_h', t: '资金费结算周期', sfx: ' h', dp: 1 },
  { k: 'funding_cap', t: '资金费上限', sfx: '', dp: 4 },
  { k: 'funding_floor', t: '资金费下限', sfx: '', dp: 4 },
  { k: 'listed_since', t: '上市时间', sfx: '', dp: 0 },
  { k: 'candidate_ev_bps', t: '候选E(风调)', sfx: ' bps', dp: 1 },
]
const PREVIEW_ROWS = [
  { k: 'funding_gap_daily_pct', t: '费差', sfx: ' %/日', dp: 4 },
  { k: 'expected_funding_daily_usdt', t: '预计资金费/日', sfx: ' U', dp: 2 },
  { k: 'est_fees_usdt', t: '手续费(4×taker)', sfx: ' U', dp: 2 },
  { k: 'est_slippage_usdt', t: '滑点估计', sfx: ' U', dp: 2 },
  { k: 'exit_capacity_25bps_usdt', t: '退出容量(25bps)', sfx: ' U', dp: 0 },
  { k: 'worst_exit_cost_usdt', t: '最坏退出成本', sfx: ' U', dp: 2 },
]

const PRODUCTS = ['C1', 'C2.H', 'C2.C', 'C2.P', 'C3.S', 'C3.R', 'C4', 'C5', 'C6', 'O1']
const kw = ref(''); const sym = ref('BTCUSDT'); const prod = ref('C2.P'); const period = ref('60')
const loading = ref(false); const note = ref(''); const dataTs = ref('')
const chartEl = ref(null); const venuesEl = ref(null)
const ctx = ref(null); const cases = ref([]); const saving = ref('')
const lastClose = ref(null)
const noteMode = ref('quick')
const quick = ref({ stage: '', basis: [], risks: [], note: '' })
const full = ref({ market_stage: '', confidence_level: '', efor: '', eagainst: '', thesis_invalidation: '',
  review_at: null, recommended_route: '', recommended_notional: 0, max_holding_time: '', decision: 'OBSERVE' })
const planDlg = ref({ open: false, caseId: null, notional: 0, venue_long: '', venue_short: '', preview: null, busy: false })
const recent = ref(JSON.parse(localStorage.getItem('mix_recent_syms') || '[]'))
let chart = null; let ro = null

const va = computed(() => ctx.value?.venues || [])
const aiOk = computed(() => !!ctx.value?.aicoin?.available)
const best = computed(() => va.value.filter(v => v.fresh && v.mid != null)
  .sort((a, b) => (a.spread_bps ?? 999) - (b.spread_bps ?? 999))[0])
const conflict = computed(() => {
  if (lastClose.value == null || best.value?.mid == null || !aiOk.value) return null
  const pct = Math.abs(lastClose.value - best.value.mid) / best.value.mid * 100
  if (pct < 0.5) return null
  return { ai: lastClose.value, official: best.value.mid, pct: pct.toFixed(2) }
})
const M = computed(() => ctx.value?.metrics || {})
function mval(k) { return M.value[k]?.value }
function mstate(k) { return M.value[k]?.state }
function mreason(k) { return M.value[k]?.reason || '' }
function msrc(k) { const s = M.value[k]?.source_status || ''; return { official_l1: '官方L1', binance_public: '币安公开', funding_feed: '费率源', instrument_spec: '合约表', opener: '决策服务' }[s] || s }

function tgl(arr, v) { const i = arr.indexOf(v); i >= 0 ? arr.splice(i, 1) : arr.push(v) }
async function suggest(q, cb) {
  if (!q) return cb(recent.value.map(s => ({ displayName: s.replace('USDT', '') + '/USDT', canonicalSymbol: s, value: s })))
  try {
    const r = await mixApi.instrumentsSearch(q)
    cb((r?.rows || []).map(x => ({ ...x, value: x.canonicalSymbol })))
  } catch (e) { cb([]) }
}
function onPick(item) { pickSym(item.canonicalSymbol) }
function pickSym(s) {
  sym.value = s
  recent.value = [s, ...recent.value.filter(x => x !== s)].slice(0, 5)
  localStorage.setItem('mix_recent_syms', JSON.stringify(recent.value))
  loadAll()
}
function openAiCoinSite() { copySym(); window.open(`https://www.aicoin.com/zh-Hans/search?keyword=${encodeURIComponent(sym.value)}`) }
function copySym() { navigator.clipboard?.writeText(sym.value); ElMessage.success(`已复制 ${sym.value}`) }
function scrollVenues() { venuesEl.value?.scrollIntoView({ behavior: 'smooth' }) }

// Asset 360 抽屉
const a360Open = ref(false)
const a360Symbol = ref('')
function openAsset360(symbol) {
  if (!symbol || symbol === '—') return
  a360Symbol.value = symbol
  a360Open.value = true
}

async function markAnomaly() {
  try {
    await mixApi.researchCaseCreate({ symbol: sym.value, review_mode: 'QUICK', market_stage: '看不清',
      risk_flags: ['单平台异常'], decision: 'OBSERVE', complete: true,
      summary_text: `标记数据异常:AiCoin ${lastClose.value} vs 官方 ${best.value?.mid}` })
    ElMessage.success('异常观察已登记'); loadCases()
  } catch (e) { ElMessage.error(e?.detail || '登记失败') }
}

async function saveQuick(decision) {
  if (!quick.value.stage) { ElMessage.warning('先选① 当前阶段'); return }
  if (!quick.value.basis.length && !quick.value.risks.length) { ElMessage.warning('②主要依据 与 ③主要风险 至少勾一项'); return }
  saving.value = decision
  try {
    const ef = [...quick.value.basis]; if (quick.value.note) ef.push(quick.value.note)
    const r = await mixApi.researchCaseCreate({ symbol: sym.value, product_code: prod.value,
      review_mode: 'QUICK', market_stage: quick.value.stage, evidence_for: ef,
      risk_flags: quick.value.risks, decision, complete: true })
    ElMessage.success(`研判已保存:${DEC_CN[decision]}`)
    quick.value = { stage: '', basis: [], risks: [], note: '' }
    loadCases()
    if (decision === 'PREPARE_PLAN') openPlan(r.id)
  } catch (e) { ElMessage.error(e?.detail || '保存失败') } finally { saving.value = '' }
}
async function saveFull() {
  saving.value = 'FULL'
  try {
    const b = {
      symbol: sym.value, product_code: prod.value, review_mode: 'FULL', market_stage: full.value.market_stage,
      confidence_level: full.value.confidence_level,
      evidence_for: full.value.efor ? [full.value.efor] : [],
      evidence_against: full.value.eagainst ? [full.value.eagainst] : [],
      thesis_invalidation: full.value.thesis_invalidation,
      review_at: full.value.review_at ? new Date(full.value.review_at).toISOString() : '',
      recommended_route: full.value.recommended_route,
      recommended_notional: full.value.recommended_notional || null,
      max_holding_time: full.value.max_holding_time, decision: full.value.decision, complete: true,
    }
    const r = await mixApi.researchCaseCreate(b)
    ElMessage.success('完整研判已保存')
    loadCases()
    if (full.value.decision === 'PREPARE_PLAN') openPlan(r.id, full.value.recommended_notional)
  } catch (e) { ElMessage.error(e?.detail || '保存失败(完整审查全必填)') } finally { saving.value = '' }
}

function openPlan(caseId, notional = 0) {
  planDlg.value = { open: true, caseId, notional: notional || 0, venue_long: '', venue_short: '', preview: null, busy: false }
  loadPreview()
}
async function loadPreview() {
  try {
    planDlg.value.preview = await mixApi.planPreview({ symbol: sym.value, notional: planDlg.value.notional || 0,
      venue_long: planDlg.value.venue_long, venue_short: planDlg.value.venue_short,
      research_case_id: planDlg.value.caseId })
    const rt = planDlg.value.preview?.route || {}
    if (!planDlg.value.venue_long && rt.venue_long) planDlg.value.venue_long = rt.venue_long
    if (!planDlg.value.venue_short && rt.venue_short) planDlg.value.venue_short = rt.venue_short
  } catch (e) { /* 预览失败不阻断,生成时后端仍校验 */ }
}
async function createPlan() {
  planDlg.value.busy = true
  try {
    const r = await mixApi.planCreate({ research_case_id: planDlg.value.caseId, notional: planDlg.value.notional,
      venue_long: planDlg.value.venue_long, venue_short: planDlg.value.venue_short })
    ElMessage.success(r?.note || `计划已进审批链(#${r?.proposal_id})`)
    planDlg.value.open = false
    router.push('/mix/today?f=' + encodeURIComponent(JSON.stringify({ q: '审批' })))
  } catch (e) { ElMessage.error(e?.detail || '生成失败') } finally { planDlg.value.busy = false }
}

async function loadK() {
  const dbKey = ctx.value?.aicoin?.db_key
  if (!dbKey || !chart) return
  loading.value = true; note.value = ''
  try {
    const r = await mixApi.aicoinKline(dbKey, period.value, 300)
    const rows = r?.data || []
    if (!rows.length) { note.value = '无K线数据'; return }
    const norm = rows.map(k => Array.isArray(k)
      ? { t: +k[0] * (String(k[0]).length < 13 ? 1000 : 1), o: +k[1], h: +k[2], l: +k[3], c: +k[4], v: +k[5] }
      : { t: +(k.ts || k.time || k.id) * (String(k.ts || k.time || k.id).length < 13 ? 1000 : 1),
          o: +k.open, h: +k.high, l: +k.low, c: +k.close, v: +(k.volume ?? k.vol ?? 0) })
    lastClose.value = norm[norm.length - 1].c
    dataTs.value = new Date(norm[norm.length - 1].t).toLocaleString('zh')
    chart.setOption({
      backgroundColor: 'transparent',
      grid: [{ left: 58, right: 14, top: 10, height: '64%' }, { left: 58, right: 14, top: '80%', height: '14%' }],
      xAxis: [
        { type: 'category', data: norm.map(k => new Date(k.t).toLocaleString('zh', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })),
          axisLine: { lineStyle: { color: '#262B33' } }, axisLabel: { color: '#5E6673', fontSize: 10 } },
        { type: 'category', gridIndex: 1, data: norm.map(k => k.t), show: false },
      ],
      yAxis: [{ scale: true, splitLine: { lineStyle: { color: '#1E2329' } }, axisLabel: { color: '#5E6673', fontSize: 10 } },
        { gridIndex: 1, show: false }],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 55, end: 100 }],
      tooltip: { trigger: 'axis', backgroundColor: '#181B21', borderColor: '#262B33', textStyle: { color: '#EAECEF', fontSize: 11 } },
      series: [
        { type: 'candlestick', data: norm.map(k => [k.o, k.c, k.l, k.h]),
          itemStyle: { color: '#0ECB81', color0: '#F6465D', borderColor: '#0ECB81', borderColor0: '#F6465D' } },
        { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: norm.map(k => k.v), itemStyle: { color: '#3a4150' } },
      ],
    })
    note.value = `${norm.length} 根 · 收 ${lastClose.value}`
  } catch (e) { note.value = e?.detail || 'K线拉取失败' } finally { loading.value = false }
}
async function loadCases() { try { cases.value = (await mixApi.researchCases(sym.value))?.rows || [] } catch (e) { cases.value = [] } }
async function loadAll() {
  loading.value = true
  try { ctx.value = await mixApi.researchContext(sym.value, prod.value) } catch (e) { ElMessage.error(e?.detail || '研判上下文加载失败') }
  loading.value = false
  loadK(); loadCases()
}
onMounted(() => {
  chart = echarts.init(chartEl.value)
  ro = new ResizeObserver(() => chart && chart.resize()); ro.observe(chartEl.value)
  const q = route.query || {}
  if (q.symbol) sym.value = String(q.symbol).toUpperCase()
  if (q.product && PRODUCTS.includes(String(q.product))) prod.value = String(q.product)
  loadAll()
  if (q.plan) openPlan(Number(q.plan))   // 今日工作深链:研判完成的工作项直达生成计划
  mixApi.uxPageview('aicoin')

})
onUnmounted(() => { ro && ro.disconnect(); chart && chart.dispose() })
</script>

<style scoped lang="scss">
.aicoin { display: flex; flex-direction: column; gap: 10px; min-height: 100%; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; min-width: 0; }
.chd2 { font-size: 12px; font-weight: 700; color: var(--mix-t1, #EAECEF); padding: 10px 14px 6px; display: flex; align-items: center; gap: 8px; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.pad { padding: 6px 14px 10px; }
.bad { color: #F6465D; } .gold { color: #F0B90B; }
.objbar { display: flex; align-items: center; gap: 10px; padding: 9px 14px; flex-wrap: wrap;
  .sym { font-size: 17px; color: var(--mix-t1, #EAECEF); } }
.tag { font-style: normal; font-size: 10px; background: var(--mix-card2, #1E2329); border-radius: 4px; padding: 2px 8px; color: var(--mix-t2, #848E9C); }
.rc { color: var(--mix-blue, #4A9CFF); cursor: pointer; margin-left: 6px; }
.sug { display: flex; align-items: baseline; gap: 8px;
  b { color: var(--mix-t1, #EAECEF); }
  .sgm { font-size: 10px; color: var(--mix-t3, #5E6673); }
  .sgp { font-size: 10px; color: #F0B90B; }
  .sga { font-size: 10px; color: var(--mix-t3, #5E6673); &.ok { color: #35b57c; } } }
.conflict { display: flex; align-items: center; gap: 10px; padding: 7px 14px; border-radius: 8px; flex-wrap: wrap;
  background: rgba(240,185,11,.08); border: 1px solid rgba(240,185,11,.3);
  .ct { color: #F0B90B; font-weight: 700; font-size: 12px; } }
.tri { flex: 1; display: grid; grid-template-columns: 560px minmax(0,1fr) 520px; gap: 10px; min-height: 460px;
  @media (max-width: 1700px) { grid-template-columns: 420px minmax(0,1fr) 420px; }
  /* 手机:三栏纵向堆叠,页面不再被固定列宽撑出视口 */
  @media (max-width: 900px) { grid-template-columns: minmax(0,1fr); min-height: 0; } }
.lcol, .mcol, .rcol { display: flex; flex-direction: column; overflow: hidden; }
.facts { display: flex; flex-direction: column; padding: 2px 14px 8px; }
.frow { display: flex; align-items: center; gap: 8px; min-height: 24px; border-bottom: 1px dashed var(--mix-border, #262B33);
  .fl { font-size: 10.5px; color: var(--mix-t3, #5E6673); width: 128px; flex: none; }
  .fsrc { margin-left: auto; font-size: 9px; color: var(--mix-t3, #5E6673); opacity: .8; }
  .inval { font-size: 10.5px; color: #FF8A3D; } }
.vhead, .vrow { display: grid; grid-template-columns: 86px 100px 1fr 60px 70px 34px; font-size: 10.5px; align-items: center; padding: 0 14px; }
.vhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 20px; border-bottom: 1px solid var(--mix-border, #262B33); margin-top: 6px; }
.vrow { height: 26px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); } &.stale { opacity: .5; } }
.r { text-align: right; padding-right: 8px; font-variant-numeric: tabular-nums; }
.m-NORMAL { color: #35b57c; } .m-WATCH { color: #F0B90B; } .m-NO_NEW_RISK { color: #FF8A3D; }
.m-REDUCE_ONLY, .m-EXIT_ONLY { color: #F6465D; } .m-FROZEN { color: #8B1E2D; }
.kchart { flex: 1; min-height: 380px; }
.aimiss { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
  b { color: var(--mix-t1, #EAECEF); font-size: 13px; }
  p { color: var(--mix-t3, #5E6673); font-size: 11px; max-width: 320px; text-align: center; } }
.quick { padding: 4px 14px 10px; display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
.qsec { display: flex; flex-direction: column; gap: 5px;
  i { font-style: normal; font-size: 10.5px; font-weight: 700; color: var(--mix-t2, #848E9C); } }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 11px; padding: 4px 10px; border-radius: 12px; cursor: pointer; user-select: none;
  background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  &.on { background: rgba(240,185,11,.12); border-color: #F0B90B; color: #F0B90B; font-weight: 700; }
  &.warn.on { background: rgba(246,70,93,.1); border-color: #F6465D; color: #F6465D; } }
.qbtns { display: flex; gap: 8px; flex-wrap: wrap; }
.qnote { font-size: 10px; color: var(--mix-t3, #5E6673); margin: 2px 0 0; }
.labform { padding: 0 14px 8px; overflow-y: auto; }
.hist { padding-bottom: 6px; }
.hhead, .hrow { display: grid; grid-template-columns: 92px 88px 96px 90px 84px 56px minmax(0,1fr);
  font-size: 10.5px; align-items: center; padding: 0 14px; }
.hhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 20px; border-bottom: 1px solid var(--mix-border, #262B33); }
.hrow { height: 26px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); } }
.lg { font-style: normal; font-size: 8.5px; color: var(--mix-t3, #5E6673); border: 1px solid var(--mix-border, #262B33); border-radius: 3px; padding: 0 3px; margin-left: 4px; }
.ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.decide { display: flex; align-items: center; gap: 16px; padding: 9px 14px; flex-wrap: wrap; }
.nums { display: flex; gap: 16px; }
.num { display: flex; flex-direction: column; gap: 1px;
  span { font-size: 9.5px; color: var(--mix-t3, #5E6673); } }
.flow { max-width: 460px; }
.pgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pv { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 8px 12px;
  .pvh { font-size: 11px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin-bottom: 4px; } }
</style>
