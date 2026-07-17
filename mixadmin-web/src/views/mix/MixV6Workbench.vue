<template>
  <!-- V6·统一策略工作台(设计帧 hExte 1:1):唯一可写策略入口;C3.S=列预设+工作流模板,非独立页面 -->
  <div class="v6wb">
    <V6StatusBar :snap="snap" :stale="stale" :can-open="canOpen" :ago="ago"/>
    <div class="body">
      <!-- 筛选条 -->
      <div class="filterbar">
        <div class="l">
          <span class="fsel" v-for="f in filters" :key="f.k">
            <i>{{ f.k }}</i>
            <el-select v-model="f.v" size="small" style="width:130px" :teleported="false">
              <el-option v-for="o in f.opts" :key="o" :label="o" :value="o"/>
            </el-select>
          </span>
        </div>
        <div class="r">
          <span class="quota">已用 {{ usedU }} / 可用 {{ freeU }} U · 数据截至 {{ asofT }}</span>
          <button class="newbtn" :disabled="!canOpen||!isOperator" :title="!isOperator?'只读账号:需操作员权限':''"
                  @click="newPlanOpen=true">＋ 新建手动计划（也走统一 Intent）</button>
        </div>
      </div>
      <!-- 工作流导航 -->
      <div class="flownav">
        <span v-for="s in FLOW" :key="s.k" class="fstep" :class="{on:flow===s.k}" @click="flow=s.k">
          {{ s.k }}<b v-if="s.n(this_counts)!=null" :class="{redn:s.k==='异常'&&s.n(this_counts)>0}">{{ s.n(this_counts) }}</b>
        </span>
      </div>
      <div class="main">
        <!-- 左·队列 172 -->
        <div class="left">
          <i class="lt">保存视图</i>
          <span v-for="v in VIEWS" :key="v" class="vitem" :class="{on:view===v}" @click="view=v">{{ v }}</span>
          <div class="ldiv"></div>
          <i class="lt">策略筛选</i>
          <span v-for="s in STRATS" :key="s.k" class="vitem s" :class="{on:strat===s.k}" @click="strat=s.k">{{ s.label }}</span>
          <div class="fillv"></div>
          <p class="lnote">选策略只改列预设与工作流阶段，不跳陌生页面</p>
        </div>
        <!-- 中·主表 -->
        <div class="center">
          <div class="tscroll">
          <div class="thead">
            <span style="width:120px">币种</span><span style="width:64px">产品</span>
            <span style="width:56px">来源</span><span style="width:64px">运行方式</span>
            <span style="width:108px">当前阶段</span><span style="width:78px">{{ isC3?'借币投入':'投入' }}</span>
            <span style="width:120px">{{ isC3?'点差·已确认收益':'预计/已确认收益' }}</span>
            <span style="width:96px">{{ isC3?'还币评估':'下一现金流' }}</span>
            <span style="width:100px">风险</span><span style="width:96px">下一步</span>
            <span class="fill">主操作</span>
          </div>
          <div class="tbody">
            <template v-for="w in rows" :key="w.work_item_id">
              <div class="trow" :class="{sel:sel?.work_item_id===w.work_item_id}" @click="sel=w">
                <span style="width:120px" class="t1b">{{ sel?.work_item_id===w.work_item_id?'▾':'▸' }} {{ w.symbol }}</span>
                <span style="width:64px" class="t2b">{{ w.strategy_code }}</span>
                <span style="width:56px" class="t2">{{ srcCn(w.source) }}</span>
                <span style="width:64px" :class="w.automation_mode==='AUTO'?'green':'amber'">{{ autoCn(w.automation_mode) }}</span>
                <span style="width:108px" :class="stageCls(w)">{{ w.stage_detail || w.workflow_stage }}</span>
                <span style="width:78px" class="t2">{{ kU(w.capital_reserved) }}</span>
                <span style="width:120px" :class="w.confirmed_pnl!=null?(w.confirmed_pnl>=0?'green':'redtxt'):'t3'">
                  {{ pnlOrEv(w) }}</span>
                <span style="width:96px" class="t2">{{ w.next_deadline || 'N/A' }}</span>
                <span style="width:100px" :class="w.risk_status?.level==='NORMAL'?'t3':'orange'">{{ w.risk_status?.level==='NORMAL'?'低':(w.risk_status?.reason||w.risk_status?.level||'N/A') }}</span>
                <span style="width:96px" class="t2">{{ w.next_action || 'N/A' }}</span>
                <span class="fill">
                  <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                                 :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                                 :state="actState[w.work_item_id+':'+primaryOf(w).code]||''"
                                 @run="(a)=>{sel=w; dispatchAct(a)}"/>
                  <button v-else class="ob" @click.stop="sel=w">查看</button>
                </span>
              </div>
              <div v-if="sel?.work_item_id===w.work_item_id && w.physical_accounts?.length" class="legrow"
                   v-for="(acct,i) in w.physical_accounts" :key="i">
                <span style="width:120px" class="t3">└ {{ acct }}</span>
                <span class="t3" style="flex:1">{{ w.workflow_template }} · 腿{{ i+1 }} ｜ owner={{ w.owner_key || 'N/A' }}</span>
              </div>
            </template>
            <EmptyState v-if="!rows.length" kind="none" title="当前视图/筛选下无工作项"
                        hint="系统自动运行中;切换上方工作流分段或清除筛选"/>
          </div>
          </div>
          <div class="tfoot">Saga/Owner/LCB/generation/交易所错误码默认不显示 → 右侧「技术详情」只读折叠 ｜ C3.S=列预设+工作流模板,非独立页面</div>
        </div>
        <!-- 右·联动详情 392 -->
        <div class="right" v-if="sel">
          <div class="rhd">
            <div class="rh1"><b>{{ sel.symbol }} · {{ sel.strategy_code }}</b>
              <span class="badge" :class="sel.automation_mode==='AUTO'?'bg':'ba'">{{ autoCn(sel.automation_mode) }}</span></div>
            <i>投入 {{ kU(sel.capital_reserved) }} · 已确认 {{ pnlText(sel.confirmed_pnl) }} · 工作项 {{ sel.work_item_id }}</i>
          </div>
          <div class="rbody">
            <div v-for="(st,i) in TIMELINE" :key="st" class="tl" :class="tlCls(i)">
              <b class="tld"></b><span>{{ st }}</span>
              <em v-if="tlCls(i)==='cur'">← 当前</em>
            </div>
            <div class="tech" @click="techOpen=!techOpen">
              <FIcon name="wrench" :size="11"/> 技术详情（只读折叠）<em>{{ techOpen?'▲':'▼' }}</em>
            </div>
            <div v-if="techOpen" class="techbody">
              <p>owner_key: {{ sel.owner_key || 'N/A' }}</p>
              <p>saga_id: {{ sel.saga_id || 'N/A' }} ｜ intent: {{ sel.position_intent_id || 'N/A' }}</p>
              <p>template: {{ sel.workflow_template || 'N/A' }} ｜ source: {{ sel.source }}</p>
              <p>ledger: {{ sel.ledger_status || 'N/A' }} ｜ as_of: {{ sel.as_of }}</p>
            </div>
            <div class="sysadv">
              <b>系统建议</b>
              <span>{{ sel.next_action || 'N/A' }}{{ sel.next_deadline ? ' · '+sel.next_deadline : '' }}</span>
            </div>
            <div class="fillv"></div>
            <!-- v2.2 五字段叙述(确定性状态机产出) -->
            <div class="narr">
              <div class="nrow"><i>发生了什么</i><span>{{ sel.what_happened || '—' }}</span></div>
              <div class="nrow"><i>系统已做</i><span>{{ sel.system_did || '—' }}</span></div>
              <div class="nrow"><i>完成条件</i><span>{{ sel.completion_condition || '—' }}</span></div>
              <div class="nrow"><i>下一触发</i><span>{{ sel.next_trigger || '—' }}</span></div>
            </div>
            <div class="acts">
              <b class="at">允许动作（服务端七元交集：能力∩角色∩风险∩阶段∩设备∩维护∩资格矩阵）</b>
              <div class="abtns">
                <PrimaryAction v-for="a in (sel.allowed_actions||[])" :key="a.code" :a="a"
                               :still-allowed="sel.still_allowed" :blocking-reason="sel.blocking_reason"
                               :state="actState[a.code]||''" @run="dispatchAct"/>
              </div>
              <p v-if="sel.product_capability && sel.product_capability!=='ACTIVE_WRITE'" class="capnote">
                能力档位：{{ CAP_CN[sel.product_capability]||sel.product_capability }}</p>
            </div>
            <p class="rnote">提升自动化=重新认证+影响预览；降级立即生效(在途腿完成或安全回滚)；同一流程同时只有一个控制权</p>
          </div>
        </div>
        <div class="right rempty" v-else><span>点击左表任意行 → 联动详情</span></div>
      </div>
      <!-- 底部汇总条 -->
      <div class="sumbar">
        <span><i>额度</i><b>{{ usedU }}/{{ quotaU }} U</b></span>
        <span><i>在管</i><b>{{ mgd }} 项</b></span>
        <span><i>待对冲</i><b :class="hedgeN>0?'redtxt':'green'">{{ hedgeN }}</b></span>
        <span><i>待还币</i><b :class="repayN>0?'amber':'green'">{{ repayN }}</b></span>
        <span><i>今日收益</i><b class="t3">N/A（账本口径见资产与收益）</b></span>
        <span><i>异常</i><b :class="abnN>0?'redtxt':'green'">{{ abnN }}{{ abnSym?' · '+abnSym:'' }}</b></span>
        <span class="fill"></span>
        <span class="mnote">维护/只减仓时：全台隐藏开仓·新借币·加仓，保留撤单/补对冲/买回/还币/减仓/平仓/修复</span>
      </div>
    </div>
    <!-- C3.S 减险动作复用坑位页同源组件(还币弹窗/平仓预演) -->
    <PartialRepayModal v-model="repayModal.open" :symbol="repayModal.symbol" @done="()=>{}"/>
    <ClosePreviewDialog v-model="closePrev.open" :symbol="closePrev.symbol"/>
    <!-- 新建手动计划(MANUAL 也走统一 Intent:补全成本/路线/风险→硬校验→DRY_RUN) -->
    <el-dialog v-model="newPlanOpen" title="新建手动计划（走统一 Intent · DRY_RUN 先行）" width="480px">
      <el-form label-width="90px">
        <el-form-item label="标的"><el-input v-model="np.symbol" placeholder="如 TONUSDT"/></el-form-item>
        <el-form-item label="产品">
          <el-select v-model="np.product" style="width:100%">
            <el-option v-for="p in ['C1','C2.H','C2.C','C3.S','C3.R','C4','C5','C6','O1']" :key="p" :value="p" :label="p"/>
          </el-select>
        </el-form-item>
        <el-form-item label="目标名义U"><el-input-number v-model="np.notional" :min="0" style="width:100%"/></el-form-item>
      </el-form>
      <p class="t3sm">手动模式不能绕过 净期望/额度/平台风险/借币保证金/多腿完整性 —— 提交后进 DRY_RUN 冷却+审批链,不直接下单。</p>
      <template #footer>
        <el-button @click="newPlanOpen=false">取消</el-button>
        <el-button type="primary" :disabled="!np.symbol" @click="createPlan">生成 DRY_RUN 提案</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { mixApi } from '../../api/mix'
import { useV6Snapshot } from '../../composables/useV6'
import V6StatusBar from '../../components/V6StatusBar.vue'
import PartialRepayModal from '../../components/rules/PartialRepayModal.vue'
import ClosePreviewDialog from '../../components/ClosePreviewDialog.vue'
import PrimaryAction from '../../components/v62/PrimaryAction.vue'
import EmptyState from '../../components/v62/EmptyState.vue'
import { useSelection } from '../../composables/useSelection'

const router = useRouter()
const { snap, stale, canOpen, isOperator, ago } = useV6Snapshot()
const flow = ref('今日待办')
const view = ref('待我处理')
const strat = ref('全部')
const sel = ref(null)
const techOpen = ref(false)
const newPlanOpen = ref(false)
const np = ref({ symbol: '', product: 'C2.H', notional: 100 })

const filters = ref([
  { k: '产品', v: '全部', opts: ['全部', 'C1', 'C2.H', 'C2.C', 'C3.S', 'C3.R', 'O1'] },
  { k: '运行方式', v: '全部(自动/辅助/手动)', opts: ['全部(自动/辅助/手动)', '自动', '辅助', '手动'] },
  { k: '验证阶段', v: '正常运行', opts: ['正常运行', 'SHADOW', 'CANARY', 'ARMED', 'CLOSE_ONLY'] },
  { k: '风险限制', v: '无', opts: ['无', '仅受限', '全部'] },
  { k: '账户/平台', v: '全部', opts: ['全部', 'binance', 'bybit', 'okx', 'gate', 'bitget', 'hyperliquid'] },
])
const FLOW = [
  { k: '今日待办', n: c => c ? (c.abnormal + c.exiting) : null },
  { k: '候选机会', n: c => c?.candidates ?? null },
  { k: '执行中', n: c => c?.executing ?? null },
  { k: '持有中', n: c => c?.holding ?? null },
  { k: '退出与还币', n: c => c?.exiting ?? null },
  { k: '异常', n: c => c?.abnormal ?? null },
  { k: '已完成', n: () => null },
]
const VIEWS = ['待我处理', '全部运行', '异常与退出', '今日需结算', '今日需还币']
const STRATS = [
  { k: '全部', label: '全部' }, { k: 'C1', label: 'C1' },
  { k: 'C2', label: 'C2.H / C2.P / C2.C' }, { k: 'C3', label: 'C3.S / C3.R' },
  { k: 'C4', label: 'C4 / C5 / C6' }, { k: 'O1', label: 'O1' },
]
const TIMELINE = ['机会通过', '额度预占', '借币', '对冲完成', '持有/结算', '退出/买回', '还币', '账本确认']
const STAGE_TL = { DISCOVERED: 0, REVIEW: 0, RESERVED: 1, EXECUTING: 2, HOLDING: 4, EXITING: 5, RECONCILING: 7, CLOSED: 7 }

const this_counts = computed(() => snap.value?.counts)
const items = computed(() => snap.value?.work_items || [])
const rows = computed(() => {
  let list = items.value
  const f = flow.value
  if (f === '候选机会') list = list.filter(w => w.workflow_stage === 'DISCOVERED')
  else if (f === '执行中') list = list.filter(w => ['RESERVED', 'EXECUTING'].includes(w.workflow_stage))
  else if (f === '持有中') list = list.filter(w => w.workflow_stage === 'HOLDING')
  else if (f === '退出与还币') list = list.filter(w => w.workflow_stage === 'EXITING')
  else if (f === '异常') list = list.filter(w => w.workflow_stage === 'RECONCILING')
  else if (f === '已完成') list = list.filter(w => w.workflow_stage === 'CLOSED')
  else list = list.filter(w => w.workflow_stage !== 'DISCOVERED' || w.next_action?.includes('受限') === false || true)
  if (strat.value !== '全部') list = list.filter(w => (w.strategy_code || '').startsWith(strat.value))
  if (view.value === '异常与退出') list = list.filter(w => ['EXITING', 'RECONCILING'].includes(w.workflow_stage))
  if (view.value === '今日需结算') list = list.filter(w => (w.next_deadline || '').includes('UTC'))
  if (view.value === '今日需还币') list = list.filter(w => (w.next_action || '').includes('还币'))
  const pf = filters.value[0].v
  if (pf !== '全部') list = list.filter(w => (w.strategy_code || '') === pf)
  const af = filters.value[1].v
  if (af !== '全部(自动/辅助/手动)') list = list.filter(w => autoCn(w.automation_mode) === af)
  const rf = filters.value[3].v
  if (rf === '仅受限') list = list.filter(w => w.risk_status?.level !== 'NORMAL')
  const vf = filters.value[4].v
  if (vf !== '全部') list = list.filter(w => (w.physical_accounts || []).some(a => String(a).includes(vf)))
  return list
})
const mgd = computed(() => (snap.value?.positions || []).length)
const hedgeN = computed(() => items.value.filter(w => (w.stage_detail || '').includes('单腿')).length)
const repayN = computed(() => items.value.filter(w => (w.next_action || '').includes('还币')).length)
const abnN = computed(() => this_counts.value?.abnormal ?? 0)
const abnSym = computed(() => items.value.find(w => w.workflow_stage === 'RECONCILING')?.symbol || '')
const usedU = computed(() => {
  const s = (snap.value?.positions || []).reduce((a, w) => a + (Number(w.capital_reserved) || 0), 0)
  return s ? s.toFixed(0) : '0'
})
const quotaU = computed(() => 'N/A')
const freeU = computed(() => 'N/A')
const asofT = computed(() => snap.value?.as_of ? new Date(snap.value.as_of).toTimeString().slice(0, 8) : 'N/A')

function autoCn(m) { return { AUTO: '自动', ASSISTED: '辅助', MANUAL: '手动' }[m] || 'N/A' }
function srcCn(s) { return { opener: '顾问', proposal: '提案', manager: '内核', coin: 'C3引擎', repair: '修复' }[s] || s }
function kU(v) { if (v == null) return 'N/A'; const n = Number(v); return n >= 1000 ? (n / 1000).toFixed(1) + 'K U' : n.toFixed(0) + ' U' }
function pnlText(v) { return v == null ? 'N/A' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)} U` }
function pnlOrEv(w) {
  if (w.confirmed_pnl != null) return `已确认 ${pnlText(w.confirmed_pnl)}`
  if (w.expected_net_return != null) return `预计 ${w.expected_net_return >= 0 ? '+' : ''}${Number(w.expected_net_return).toFixed(1)}bps/d`
  return 'N/A'
}
function stageCls(w) { return w.workflow_stage === 'RECONCILING' ? 'redtxt' : (w.workflow_stage === 'EXITING' ? 'amber' : 'green') }
function tlCls(i) {
  if (!sel.value) return ''
  const cur = STAGE_TL[sel.value.workflow_stage] ?? 0
  return i < cur ? 'done' : (i === cur ? 'cur' : '')
}
const isC3 = computed(() => strat.value === 'C3')
// 行内主操作=服务端 allowed_actions 的第一个 primary(无 primary 取第一个)——前端不猜
function primaryOf(w) {
  const acts = w.allowed_actions || []
  return acts.find(a => a.kind === 'primary') || acts[0] || null
}
// V6.1 §3:按钮由服务端 allowed_actions 决定,前端只做动作分发,不猜可用性
const CAP_CN = { ACTIVE_WRITE: '当前可写', ACTIVE_READ: '已接入只读', SHADOW: '影子验证',
                 PLANNED: '尚未启用', BLOCKED: '被风险/维护阻断', DEPRECATED: '即将淘汰' }
// 提交三态:code→''/loading/failed(服务端确认前不做假成功迁移)
const actState = ref({})
// V6.2 selection:URL={wi,view,tab,f} / session={scroll,展开,列宽}
const selst = useSelection('workbench')
watch(sel, w => { selst.wi.value = w?.work_item_id || '' })
watch([flow, strat, view], () => {
  selst.filters.value = { flow: flow.value, strat: strat.value, v: view.value }
})
onMounted(() => {
  mixApi.uxPageview('workbench')   // M5 收敛门槛数据:本页冻结,连续两周为0→收菜单
  const f = selst.filters.value
  if (f.flow) flow.value = f.flow
  if (f.strat) strat.value = f.strat
  if (f.v) view.value = f.v
})
watch(items, list => {   // 快照到达后按 URL 恢复选中行
  if (selst.wi.value && !sel.value) {
    const w = list.find(x => x.work_item_id === selst.wi.value)
    if (w) sel.value = w
  }
}, { once: false })
const repayModal = ref({ open: false, symbol: '' })
const closePrev = ref({ open: false, symbol: '' })
function dispatchAct(a) {
  const w = sel.value
  if (!w || !a.wired) return
  switch (a.code) {
    case 'opportunity_to_workbench': return oppSend(w)
    case 'opportunity_watch': return oppAct2(w, 'opportunity_watch')
    case 'opportunity_ignore': return oppAct2(w, 'opportunity_ignore')
    case 'view_basis': case 'view': techOpen.value = true; return
    case 'proposal_approve': case 'proposal_reject': return router.push('/mix/dashboard')
    case 'workitem_takeover': return takeover(w)
    case 'workitem_ack': return ack(w)
    case 'close_preview': closePrev.value = { open: true, symbol: w.symbol }; return
    case 'c3_partial_repay': repayModal.value = { open: true, symbol: w.symbol }; return
    case 'c3_force_close': return c3Close(w)
    case 'goto_risk_center': return router.push('/mix/venuerisk')
  }
}
async function oppAct2(w, ctype) {
  try {
    const r = await mixApi.v6Command({ command_type: ctype, params: { symbol: w.symbol, strategy_code: w.strategy_code } })
    ElMessage.success(r?.result?.note || '已登记')
  } catch (e) { ElMessage.error(e?.detail || '被拒绝') }
}
async function c3Close(w) {
  try {
    await ElMessageBox.confirm(`对 ${w.symbol} 执行平仓买回（经 coin 权威状态机,含还币闸）？`, '平仓买回', { type: 'warning' })
  } catch { return }
  try {
    const r = await mixApi.coinAction(w.symbol, 'force_close')
    ElMessage.success(r?.note || '已提交 coin 权威执行')
  } catch (e) { ElMessage.error(e?.detail || e?.error || '被拒绝(coin 状态机权威校验)') }
}
async function oppSend(w) {
  // 提交三态:loading→服务端确认→成功;失败复位为 failed(可重试),严禁假成功迁移
  const k = w.work_item_id + ':opportunity_to_workbench'
  actState.value = { ...actState.value, [k]: 'loading', opportunity_to_workbench: 'loading' }
  try {
    const r = await mixApi.v6Command({ command_type: 'opportunity_to_workbench',
      params: { symbol: w.symbol, strategy_code: w.strategy_code } })
    ElMessage.success(r?.result?.note || '已登记(服务端已确认)')
    actState.value = { ...actState.value, [k]: '', opportunity_to_workbench: '' }
  } catch (e) {
    ElMessage.error(e?.detail || '被拒绝(风险闸/维护闸)')
    actState.value = { ...actState.value, [k]: 'failed', opportunity_to_workbench: 'failed' }
  }
}
async function takeover(w) {
  try {
    const r = await mixApi.v6Command({ command_type: 'workitem_takeover',
      scope: `CORE_POOL:${w.strategy_code}:${w.symbol}`,
      params: { symbol: w.symbol, strategy_code: w.strategy_code, reason: '工作台人工接管' } })
    ElMessage.success(`接管成功 epoch=${r?.result?.writer_epoch}(旧口令已作废)`)
  } catch (e) { ElMessage.error(e?.detail || '接管失败') }
}
async function ack(w) {
  try { await mixApi.v6Command({ command_type: 'workitem_ack', params: { work_item_id: w.work_item_id } }); ElMessage.success('已确认') }
  catch (e) { ElMessage.error(e?.detail || '失败') }
}
async function createPlan() {
  try {
    const r = await mixApi.v6Command({ command_type: 'proposal_dry_run', automation_mode: 'MANUAL',
      params: { symbol: np.value.symbol.toUpperCase(), product: np.value.product, target_notional: np.value.notional } })
    ElMessage.success('DRY_RUN 提案已建:冷却→审批,不直接下单')
    newPlanOpen.value = false
  } catch (e) { ElMessage.error(e?.detail || e?.error || '被拒绝') }
}
</script>
<style scoped>
.v6wb{height:100%;display:flex;flex-direction:column;background:var(--mix-bg);min-height:0}
.body{flex:1;display:flex;flex-direction:column;gap:8px;padding:8px 12px;min-height:0}
.filterbar{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.filterbar .l{display:flex;gap:6px;flex-wrap:wrap}
.fsel{display:inline-flex;align-items:center;gap:5px;background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:5px;padding:2px 6px 2px 9px}
.fsel i{font-size:9.5px;color:var(--mix-t3);font-style:normal;white-space:nowrap}
.filterbar .r{display:flex;gap:8px;align-items:center}
.quota{font-size:10.5px;color:var(--mix-t2)}
.newbtn{height:34px;padding:0 13px;border-radius:6px;background:#F0B90B1F;border:1px solid #F0B90B4D;color:var(--mix-accent);font-size:11.5px;font-weight:700;cursor:pointer}
.newbtn:disabled{opacity:.45;cursor:not-allowed}
.flownav{display:flex;gap:2px;background:var(--mix-panel);border-radius:6px;padding:2px}
.fstep{flex:1;height:32px;display:flex;align-items:center;justify-content:center;gap:5px;font-size:11.5px;color:var(--mix-t2);border-radius:5px;cursor:pointer}
.fstep.on{background:var(--mix-card2);color:var(--mix-t1);font-weight:700}
.fstep b{font-size:9.5px;background:var(--mix-card2);border-radius:7px;padding:0 6px;color:var(--mix-t1)}
.fstep b.redn{background:#F6465D26;color:var(--mix-red)}
.main{flex:1;display:flex;gap:8px;min-height:0}
.left{width:172px;flex:none;background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;padding:8px 6px;display:flex;flex-direction:column;gap:2px;overflow:auto}
.lt{font-size:9px;font-weight:700;color:var(--mix-t3);font-style:normal;padding:4px 8px 2px}
.vitem{font-size:10.5px;color:var(--mix-t2);height:30px;display:flex;align-items:center;padding:0 8px;border-radius:5px;cursor:pointer}
.vitem.s{height:28px;font-size:10px}
.vitem.on{background:#F0B90B1F;color:var(--mix-accent);font-weight:700}
.vitem.s.on{background:var(--mix-card2);color:var(--mix-t1)}
.ldiv{height:1px;background:var(--mix-border);margin:6px 0}
.lnote{font-size:8.5px;color:var(--mix-t3);line-height:1.5;padding:0 8px;margin:0}
.center{flex:1;min-width:0;background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;display:flex;flex-direction:column;overflow:hidden}
/* 表头+表体同滚动容器:小屏横向滚动而不是压缩裁切列;表头 sticky 跟随 */
.tscroll{flex:1;overflow:auto;min-height:0}
.thead,.trow,.legrow{min-width:1040px}
.thead span,.trow span{flex-shrink:0}
.thead .fill,.trow .fill{flex-shrink:1}
.thead{display:flex;align-items:center;height:24px;background:var(--mix-panel);border-bottom:1px solid var(--mix-border);position:sticky;top:0;z-index:1}
.thead span{font-size:8.5px;font-weight:700;color:var(--mix-t3);padding:0 7px;white-space:nowrap;overflow:hidden}
.tbody{min-height:0}
.trow{display:flex;align-items:center;height:32px;border-bottom:1px solid var(--mix-border);cursor:pointer}
.trow span{font-size:9.5px;padding:0 7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.trow.sel{background:var(--mix-card2);border-left:2px solid var(--mix-blue)}
.legrow{display:flex;align-items:center;height:26px;border-bottom:1px solid var(--mix-border);background:#00000022}
.legrow span{font-size:9px;padding:0 7px 0 14px}
.tfoot{font-size:8.5px;color:var(--mix-t3);padding:4px 10px;border-top:1px solid var(--mix-border)}
.right{width:392px;flex:none;background:var(--mix-card);border:1px solid var(--mix-blue);border-radius:8px;display:flex;flex-direction:column;overflow:hidden}
.right.rempty{border-color:var(--mix-border);align-items:center;justify-content:center;color:var(--mix-t3);font-size:11px}
.rhd{padding:8px 12px 6px;border-bottom:1px solid var(--mix-border)}
.rh1{display:flex;align-items:center;justify-content:space-between}
.rh1 b{font-size:13px;color:var(--mix-t1)}
.badge{font-size:9px;font-weight:700;border-radius:4px;padding:2px 7px}
.badge.bg{background:#0ECB8114;color:var(--mix-green)}
.badge.ba{background:#F0B90B1F;color:var(--mix-accent)}
.rhd i{font-size:9.5px;color:var(--mix-t3);font-style:normal}
.rbody{flex:1;display:flex;flex-direction:column;gap:5px;padding:6px 12px 8px;overflow:auto;min-height:0}
.tl{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:10.5px;color:var(--mix-t3)}
.tl .tld{width:8px;height:8px;border-radius:50%;background:var(--mix-border);flex:none}
.tl.done{color:var(--mix-t2)} .tl.done .tld{background:var(--mix-green)}
.tl.cur{color:var(--mix-t1);font-weight:700} .tl.cur .tld{background:var(--mix-accent);box-shadow:0 0 0 3px #F0B90B33}
.tl em{font-size:9px;color:var(--mix-accent);font-style:normal;margin-left:auto}
.tech{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px;font-size:10px;color:var(--mix-t2);cursor:pointer;display:flex;justify-content:space-between}
.techbody{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px}
.techbody p{font-size:9px;color:var(--mix-t3);margin:2px 0;word-break:break-all}
.sysadv{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:7px 10px;display:flex;flex-direction:column;gap:2px}
.sysadv b{font-size:10px;color:var(--mix-t1)}
.sysadv span{font-size:9.5px;color:var(--mix-t2)}
.acts{display:flex;flex-direction:column;gap:5px}
.at{font-size:9.5px;color:var(--mix-t3)}
.abtns{display:flex;flex-wrap:wrap;gap:5px}
.ob{font-size:10px;font-weight:700;padding:5px 10px;border-radius:5px;border:1px solid var(--mix-border);background:var(--mix-card2);color:var(--mix-t1);cursor:pointer}
.ob.gold{background:#F0B90B1F;border-color:#F0B90B4D;color:var(--mix-accent)}
.ob.red{background:#F6465D14;border-color:#F6465D66;color:var(--mix-red)}
.ob.dim,.ob:disabled{opacity:.4;cursor:not-allowed}
.blockr{font-size:9.5px;color:#FF8A3D;margin:2px 0 0}
/* v2.2 五字段叙述块 */
.narr{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:7px 10px;display:flex;flex-direction:column;gap:4px}
.nrow{display:flex;gap:8px;font-size:10px}
.nrow i{color:var(--mix-t3);font-style:normal;flex:none;width:56px;font-size:9px}
.nrow span{color:var(--mix-t2);line-height:1.4}
.capnote{font-size:9px;color:var(--mix-t3);margin:0}
.rnote{font-size:8.5px;color:var(--mix-t3);line-height:1.45;margin:0}
.sumbar{height:36px;background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;display:flex;align-items:center;gap:16px;padding:0 12px;flex:none;overflow-x:auto;overflow-y:hidden}
.sumbar span{display:inline-flex;gap:5px;align-items:center;white-space:nowrap}
.sumbar i{font-size:9.5px;color:var(--mix-t3);font-style:normal}
.sumbar b{font-size:10.5px;color:var(--mix-t1)}
.mnote{font-size:9px;color:var(--mix-t3)}
.fill{flex:1;min-width:0}.fillv{flex:1}
.t1b{color:var(--mix-t1);font-weight:700}.t2b{color:var(--mix-t2);font-weight:700}
.t2{color:var(--mix-t2)}.t3{color:var(--mix-t3)}.t3sm{font-size:10px;color:var(--mix-t3)}
.green{color:var(--mix-green)}.redtxt{color:var(--mix-red)}.amber{color:var(--mix-accent)}.orange{color:#FF8A3D}
@media (max-width:1680px){ .right{width:340px} }
@media (max-width:1500px){ .right{width:300px} .left{width:150px} }
@media (max-width:1280px){ .right{display:none} }
@media (max-width:1000px){ .left{display:none} }
</style>
