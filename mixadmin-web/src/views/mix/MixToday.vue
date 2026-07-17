<template>
  <!-- V6.2 今日工作(帧 D2GIj):中控台+三墙+工作台的合体——唯一日常入口。
       一份快照/七段流程条/三视图(三栏|页签|墙聚焦)/行点击→右抽屉六段,全程不跳页。 -->
  <div class="today">
    <V6StatusBar :snap="snap" :stale="stale" :can-open="canOpen" :ago="ago"/>
    <div class="body">
      <div class="railrow">
        <ProcessRail class="railfill" :steps="railSteps" @pick="pickQueue"/>
        <!-- 视图切换:轻列表(默认)|深表格(/mix/work?view=table,工作台主表能力并入统一外壳) -->
        <span class="vswitch">
          <a :class="{on:viewMode==='list'}" @click="viewMode='list'">列表</a>
          <a :class="{on:viewMode==='table'}" @click="viewMode='table'">表格</a>
        </span>
        <!-- 手动计划泛产品化:全产品统一走 研判先行→DRY_RUN 链路 -->
        <button class="planbtn" @click="npOpen=true">＋ 手动计划</button>
        <!-- §9.2:训练通过后菜单收敛,入口迁到这里(仍可主动进入演练) -->
        <button v-if="trainOk" class="trainbtn" @click="$router.push('/mix/training')"><FIcon name="cap" :size="12"/> 训练/演练</button>
      </div>
      <!-- 深表格视图:与轻列表同一快照同一抽屉,队列过滤共用流程条 -->
      <WorkTable v-if="viewMode==='table'" :items="tableItems" :row-state="rowState" :sel-id="selId"
                 @open="openItem" @run="runAct"/>
      <!-- 窄屏页签(≥1360 自动隐藏,三栏并排) -->
      <div v-if="viewMode==='list'" class="vtabs">
        <span v-for="v in ['机会','持仓','风险']" :key="v" class="vt" :class="{on:vtab===v}" @click="vtab=v">{{ v }}</span>
        <span class="wallbtns">
          <a v-for="w in WALLS" :key="w.k" @click="openWall(w.k)">{{ w.t }}</a>
        </span>
      </div>
      <div v-if="viewMode==='list'" class="cols" :data-vtab="vtab" :data-focus="focusCol">
        <!-- 栏1·机会 -->
        <div class="col c-opp">
          <div class="chd"><b>机会</b><i>候选 {{ snap?.counts?.candidates_raw ?? '—' }} → 过闸 {{ opps.length }}</i></div>
          <div class="list" ref="oppList">
            <div v-for="w in opps" :key="w.work_item_id" class="row" :class="{sel:selId===w.work_item_id, submitting:rowState[w.work_item_id]==='loading'}"
                 @click="openItem(w)">
              <b class="sym">{{ w.symbol }} · {{ w.strategy_code }}</b>
              <span class="ev" :class="(w.expected_net_return||0)>=0?'up':'dn'">{{ evT(w) }}</span>
              <span class="fill"></span>
              <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                             :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                             :state="rowState[w.work_item_id]||''" @run="(a)=>runAct(w,a)"/>
            </div>
            <EmptyState v-if="!opps.length" kind="none" title="暂无过闸候选" hint="顾问与 LAB 持续扫描中"/>
          </div>
        </div>
        <!-- 栏2·持仓 -->
        <div class="col c-pos">
          <div class="chd"><b>持仓 · 一行=一个经济组合</b><i>{{ queueNote }}</i></div>
          <div class="list">
            <div v-for="w in posShown" :key="w.work_item_id" class="row tall" :class="{sel:selId===w.work_item_id, bad:w.workflow_stage==='RECONCILING'}"
                 @click="openItem(w)">
              <div class="r1">
                <b class="sym">{{ w.symbol }} · {{ w.strategy_code }}</b>
                <span class="st" :class="stCls(w)">{{ w.stage_detail || w.workflow_stage }}</span>
                <!-- §6.3 点差保护=一等状态,不藏详情;shadow 评估,退出决策仍人工 -->
                <span v-if="w.risk_protection_state && w.risk_protection_state!=='NORMAL'"
                      class="prot" :class="w.risk_protection_state"
                      :title="'点差保护(shadow) · 预算余 '+(w.hard_loss_budget_remaining??'—')+'U · 回本 '+(w.recovery_windows??'—')+'窗'">
                  <FIcon name="shield" :size="10"/> {{ PROT_CN[w.risk_protection_state]||w.risk_protection_state }}</span>
                <span class="fill"></span>
                <span class="ddl">{{ w.next_deadline || '' }}</span>
                <PrimaryAction v-if="primaryOf(w)" :a="primaryOf(w)" sz="sm"
                               :still-allowed="w.still_allowed" :blocking-reason="w.blocking_reason"
                               :state="rowState[w.work_item_id]||''" @run="(a)=>runAct(w,a)"/>
              </div>
              <div class="r2">{{ w.what_happened }}</div>
            </div>
            <EmptyState v-if="!posShown.length" kind="none" :title="`「${queueLabel}」队列为空`" hint="点流程条其它分段查看"/>
          </div>
        </div>
        <!-- 栏3·风险 -->
        <div class="col c-risk">
          <div class="chd"><b>风险 · 必须处理优先</b></div>
          <div class="list pad">
            <div v-if="p0item" class="must" @click="openItem(p0item)">
              <b>{{ p0item.symbol }} · {{ p0item.stage_detail }}</b>
              <div class="qa"><i>发生了什么</i><span>{{ p0item.what_happened }}</span></div>
              <div class="qa"><i>系统已做</i><span>{{ p0item.system_did }}</span></div>
              <div class="qa"><i>你需要做什么</i><span>{{ p0item.next_action }}</span></div>
            </div>
            <div v-else-if="p0inc" class="must">
              <b>P0 · {{ p0inc.venue }} {{ p0inc.title }}</b>
              <div class="qa"><i>详情</i><span>{{ (p0inc.detail||'').slice(0,90) }}</span></div>
              <div class="qa"><i>处置</i><span><a @click="deepRisk">进风险与账务·风险事件 →</a></span></div>
            </div>
            <div v-else class="okline"><FIcon name="check" :size="12"/> 当前无必须处理事件</div>
            <div class="rrow"><b>平台/账户限制 · {{ restrictedN }}</b><span>{{ restrictedN? '已停新增·详情见风险事件' : '全部平台正常' }}</span></div>
            <div class="rrow" :class="{warn:protHotN>0}"><b>点差保护 · {{ protHotN? protHotN+' 项越线' : '全部正常' }}</b>
              <span>{{ protNote }}</span></div>
            <div class="rrow"><b>维护排空 · {{ maintT }}</b></div>
            <div class="rrow" :class="{warn:abnN>0}"><b>账目核对 · {{ abnN }} 项待清</b>
              <span>{{ abnN? '见异常队列' : '账本投影无待清差异' }}</span></div>
            <div class="fillv"></div>
            <button class="freeze" :disabled="pausing" @click="pauseNew"><FIcon name="pause" :size="12"/> 暂停开新仓（减险·立即）</button>
          </div>
        </div>
      </div>
    </div>
    <!-- 六段抽屉(帧 eTSxn 规格):不跳页,技术详情单独折叠 -->
    <el-drawer v-model="drawerOpen" :title="(sel?.symbol||'')+' · '+(sel?.strategy_code||'')" size="440px"
               @closed="selst.wi.value=''">
      <div v-if="sel" class="dw">
        <div class="dsec"><i>当前结论</i>
          <p>{{ sel.workflow_stage==='DISCOVERED' ? evT(sel)+' · '+(sel.next_action||'') : (sel.stage_detail||'') }}</p></div>
        <div class="dsec"><i>研判依据 / AiCoin</i>
          <p><span v-if="sel.research_status && sel.research_status!=='NOT_REQUIRED'" class="rs" :class="sel.research_status">
              研判{{ {PENDING:'待完成',COMPLETED:'已完成',EXPIRED:'已过期(需复核)'}[sel.research_status]||sel.research_status }}
              <template v-if="sel.next_review_at"> · 复核至 {{ (sel.next_review_at||'').slice(5,16) }}</template></span>
            {{ sel.what_happened }} <a class="dl" @click="$router.push({path:'/mix/aicoin',query:{symbol:sel.symbol}})">打开研判 →</a></p></div>
        <div class="dsec"><i>成本与预计收益</i>
          <p>投入 <ValueCell :value="sel.capital_reserved" :state="sel.data_state?.capital_reserved" suffix=" U"/> ·
             预期 <ValueCell :value="sel.expected_net_return" :state="sel.data_state?.expected_net_return" suffix=" bps/日" :dp="1"/> ·
             已确认 <ValueCell :value="sel.confirmed_pnl" :state="sel.data_state?.confirmed_pnl" suffix=" U" :dp="1"/></p></div>
        <div class="dsec"><i>平台与账户风险</i>
          <p :class="sel.risk_status?.level==='NORMAL'?'':'warn'">{{ sel.risk_status?.level==='NORMAL' ? '低 · 全所正常' : (sel.risk_status?.reason || sel.risk_status?.level) }}</p>
          <p v-if="sel.risk_protection_state && sel.risk_protection_state!=='NORMAL'" class="warn">
            <FIcon name="shield" :size="11"/> 点差保护[{{ PROT_CN[sel.risk_protection_state]||sel.risk_protection_state }}](shadow):
            真实退出盈亏 <ValueCell :value="sel.closeout_pnl_net" suffix=" U" :dp="2"
              :state="sel.closeout_pnl_net==null?'NOT_CONNECTED':undefined"/> ·
            预算余量 <ValueCell :value="sel.hard_loss_budget_remaining" suffix=" U" :dp="2"
              :state="sel.hard_loss_budget_remaining==null?'NOT_YET_AVAILABLE':undefined"/> ·
            回本 <ValueCell :value="sel.recovery_windows" suffix=" 窗" :dp="1"
              :state="sel.recovery_windows==null?'NOT_YET_AVAILABLE':undefined"/></p></div>
        <div class="dsec"><i>系统已经做了什么</i><p>{{ sel.system_did }}</p></div>
        <div class="dsec"><i>完成条件与下一步</i><p>{{ sel.completion_condition }}<br/>触发:{{ sel.next_trigger }}</p></div>
        <div class="dsec"><i>深链</i><p>
          <a class="dl" @click="$router.push({path:'/mix/history',query:{symbol:sel.symbol}})">交易与核对 →</a>
          <a class="dl" @click="deepRisk">风险事件 →</a>
          <a class="dl" @click="$router.push('/mix/report')">资产收益 →</a></p></div>
        <div class="dacts">
          <PrimaryAction v-for="a in (sel.allowed_actions||[])" :key="a.code" :a="a"
                         :still-allowed="sel.still_allowed" :blocking-reason="sel.blocking_reason"
                         :state="rowState[sel.work_item_id]||''" @run="(x)=>runAct(sel,x)"/>
        </div>
        <div class="tech" @click="techOpen=!techOpen"><FIcon name="wrench" :size="11"/> 技术详情（只读折叠）{{ techOpen?'▲':'▼' }}</div>
        <div v-if="techOpen" class="techb">
          <p>owner: {{ sel.owner_key||'N/A' }} ｜ saga: {{ sel.saga_id||'N/A' }} ｜ epoch: {{ sel.control_epoch??'N/A' }}</p>
          <p>runtime: {{ sel.runtime_stage }} ｜ 能力: {{ sel.product_capability }} ｜ rv: {{ sel.row_version }}</p>
        </div>
      </div>
    </el-drawer>
    <PartialRepayModal v-model="repay.open" :symbol="repay.symbol"/>
    <ClosePreviewDialog v-model="closeP.open" :symbol="closeP.symbol"/>
    <!-- 手动计划(泛产品):研判先行——本弹窗只指路,不直接建计划 -->
    <el-dialog v-model="npOpen" title="新建手动计划（研判先行 · 全产品同一链路）" width="440px">
      <el-form label-width="80px" size="small">
        <el-form-item label="标的"><el-input v-model="np.symbol" placeholder="如 TONUSDT" @input="np.symbol=np.symbol.toUpperCase()"/></el-form-item>
        <el-form-item label="产品">
          <el-select v-model="np.product" style="width:100%">
            <el-option v-for="p in ['C1','C2.H','C2.C','C2.P','C3.S','C3.R','C4','C5','C6','O1']" :key="p" :value="p"/>
          </el-select>
        </el-form-item>
      </el-form>
      <p class="npnote">流程:研判(阶段/依据/风险/结论=准备计划)→ 生成计划 → DRY_RUN 冷却 → 二次认证 → shadow 终态。
        证据先行,任何产品的手动计划都必须挂研判案件。</p>
      <template #footer>
        <el-button @click="npOpen=false">取消</el-button>
        <el-button type="primary" :disabled="!np.symbol" @click="gotoResearch">去研判并生成计划 →</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { mixApi } from '../../api/mix'
import { useV6Snapshot } from '../../composables/useV6'
import { useSelection } from '../../composables/useSelection'
import V6StatusBar from '../../components/V6StatusBar.vue'
import ProcessRail from '../../components/v62/ProcessRail.vue'
import PrimaryAction from '../../components/v62/PrimaryAction.vue'
import ValueCell from '../../components/v62/ValueCell.vue'
import EmptyState from '../../components/v62/EmptyState.vue'
import WorkTable from '../../components/v62/WorkTable.vue'
import PartialRepayModal from '../../components/rules/PartialRepayModal.vue'
import ClosePreviewDialog from '../../components/ClosePreviewDialog.vue'

const route = useRoute()
const router = useRouter()
const { snap, stale, canOpen, ago, refetch } = useV6Snapshot()
const selst = useSelection('today')
const vtab = ref('持仓')
const queue = ref('全部')
const sel = ref(null)
const selId = computed(() => sel.value?.work_item_id || '')
const drawerOpen = computed({ get: () => !!sel.value, set: v => { if (!v) sel.value = null } })
const techOpen = ref(false)
const rowState = ref({})
const pausing = ref(false)
const repay = ref({ open: false, symbol: '' })
const closeP = ref({ open: false, symbol: '' })
const WALLS = [{ k: 'market', t: '屏1' }, { k: 'exec', t: '屏2' }, { k: 'risk', t: '屏3' }]
// §9.2 训练通过→今日工作出现「训练/演练」按钮(菜单侧同步收敛,Layout 负责)
const trainOk = ref(false)
mixApi.v6Training().then(r => { trainOk.value = !!r?.certified }).catch(() => {})
// 视图模式:list 轻列表 | table 深表格(工作台主表并入统一外壳);focusCol=聚焦视图(§3.1)
const viewMode = ref('list')
const focusCol = ref('')
// 手动计划入口(泛产品,研判先行)
const npOpen = ref(false)
const np = ref({ symbol: '', product: 'C2.P' })
function gotoResearch() {
  npOpen.value = false
  router.push({ path: '/mix/aicoin', query: { symbol: np.value.symbol, product: np.value.product } })
}
const tableItems = computed(() => {
  let list = items.value
  if (queue.value !== '全部' && QUEUES[queue.value]) list = list.filter(w => QUEUES[queue.value].includes(w.workflow_stage))
  return list
})
// §8 点差保护摘要(shadow):WATCH 不计入越线,NO_ADD 起算
const PROT_CN = { WATCH: '观察', NO_ADD: '禁加仓', REDUCE_REQUIRED: '需减仓', EXIT_REQUIRED: '需退出' }
const protHotN = computed(() => {
  const c = snap.value?.risk_exit_summary?.counts || {}
  return (c.NO_ADD || 0) + (c.REDUCE_REQUIRED || 0) + (c.EXIT_REQUIRED || 0)
})
const protNote = computed(() => {
  const c = snap.value?.risk_exit_summary?.counts || {}
  const parts = Object.entries(c).filter(([k]) => k !== 'NORMAL').map(([k, v]) => `${PROT_CN[k] || k}${v}`)
  return parts.length ? parts.join(' · ') + '(shadow评估·退出仍人工)' : '在管组合退出估值全部在预算内'
})

const items = computed(() => snap.value?.work_items || [])
const opps = computed(() => items.value.filter(w => w.workflow_stage === 'DISCOVERED'))
const abn = computed(() => items.value.filter(w => w.workflow_stage === 'RECONCILING'))
const abnN = computed(() => abn.value.length)
const p0item = computed(() => abn.value[0] || null)
const p0inc = computed(() => (snap.value?.incidents || []).find(i => i.severity === 'fatal') || null)
const restrictedN = computed(() => [...new Set((snap.value?.incidents || []).filter(i => i.severity === 'fatal').map(i => i.venue))].length)
const maintT = computed(() => { const s = snap.value?.site_maintenance_state; return (!s || s === 'NORMAL' || s === 'CLOSED') ? '无进行中' : s })

const QUEUES = { 机会: ['DISCOVERED'], 人工研判: ['RESEARCH'], 审批: ['REVIEW', 'RESERVED'], 执行: ['EXECUTING'],
                 持有: ['HOLDING'], 退出与还币: ['EXITING'], 异常: ['RECONCILING'], 核对: ['RECONCILING'] }
const railSteps = computed(() => {
  const c = (sts) => items.value.filter(w => sts.includes(w.workflow_stage)).length
  const cur = queue.value
  const mk = (label, sts, extra = {}) => ({ key: label, label, count: c(sts),
    state: cur === label ? 'current' : (extra.state || (c(sts) > 0 ? 'done' : 'todo')) })
  const steps = []
  if (abnN.value > 0) steps.push({ key: '异常', label: '异常', count: abnN.value, state: cur === '异常' ? 'current' : 'error' })
  // V6.2 PATCH-01 §3.1:机会→人工研判→审批→…;C2.P 必经研判,C2.H 可主动送研判
  steps.push(mk('机会', ['DISCOVERED']), mk('人工研判', ['RESEARCH']), mk('审批', ['REVIEW', 'RESERVED']),
             mk('执行', ['EXECUTING']), mk('持有', ['HOLDING']), mk('退出与还币', ['EXITING']),
             { key: '核对', label: '核对', count: 0, state: cur === '核对' ? 'current' : 'todo' })
  return steps
})
function pickQueue(k) { queue.value = queue.value === k ? '全部' : k; if (k === '机会') vtab.value = '机会'; else vtab.value = '持仓' }
const queueLabel = computed(() => queue.value)
const queueNote = computed(() => queue.value === '全部' ? '进行中全量' : `已按「${queue.value}」过滤 · 点流程条取消`)
const posShown = computed(() => {
  let list = items.value.filter(w => w.workflow_stage !== 'DISCOVERED')
  if (queue.value !== '全部' && QUEUES[queue.value]) list = list.filter(w => QUEUES[queue.value].includes(w.workflow_stage))
  return list.sort((a, b) => (b.workflow_stage === 'RECONCILING') - (a.workflow_stage === 'RECONCILING'))
})

function evT(w) { const v = w.expected_net_return; return v == null ? '—' : `${v>=0?'+':''}${Number(v).toFixed(1)} bps/日` }
function stCls(w) { return w.workflow_stage === 'RECONCILING' ? 'dn' : (w.workflow_stage === 'EXITING' ? 'amber' : 'up') }
function primaryOf(w) { const a = w.allowed_actions || []; return a.find(x => x.kind === 'primary') || a[0] || null }
function openItem(w) { sel.value = w; selst.wi.value = w.work_item_id }
function openWall(k) { window.open(`/wall/${k}?token=${localStorage.getItem('mix_token')||''}`, `wall-${k}`) }
function deepRisk() { router.push({ path: '/mix/venuerisk' }) }

async function runAct(w, a) {
  const id = w.work_item_id
  switch (a.code) {
    case 'close_preview': closeP.value = { open: true, symbol: w.symbol }; return
    case 'c3_partial_repay': repay.value = { open: true, symbol: w.symbol }; return
    case 'goto_risk_center': deepRisk(); return
    case 'view': case 'view_basis': openItem(w); return
    case 'proposal_approve': case 'proposal_reject': router.push('/mix/dashboard'); return
    // C2.P 人工研判(V6.2 PATCH-01):研判与生成计划都在 AiCoin 研判工作台完成
    case 'open_research': router.push({ path: '/mix/aicoin', query: { symbol: w.symbol } }); return
    case 'create_manual_plan':
      router.push({ path: '/mix/aicoin', query: { symbol: w.symbol, plan: w.research_case_id || '' } }); return
  }
  // 提交三态:loading→服务端确认;失败=failed 可重试,绝不假成功迁移
  rowState.value = { ...rowState.value, [id]: 'loading' }
  try {
    const r = await mixApi.v6Command({ command_type: a.code,
      params: { symbol: w.symbol, strategy_code: w.strategy_code, work_item_id: id } })
    ElMessage.success(r?.result?.note || '已确认')
    rowState.value = { ...rowState.value, [id]: '' }
    refetch()   // 服务端确认后立即拉快照→行随真实状态原地迁移(非乐观更新)
  } catch (e) {
    ElMessage.error(e?.detail || e?.error || '被拒绝')
    rowState.value = { ...rowState.value, [id]: 'failed' }
  }
}
async function pauseNew() {
  pausing.value = true
  try { await mixApi.v6Command({ command_type: 'pause_new_risk', params: { reason: '今日工作:暂停新增' } }); ElMessage.success('已提交暂停新增(风险权威≤30s合并)') }
  catch (e) { ElMessage.error(e?.detail || '失败') } finally { pausing.value = false }
}
// selection 恢复:URL wi/tab/queue
watch(items, list => {
  if (selst.wi.value && !sel.value) {
    const w = list.find(x => x.work_item_id === selst.wi.value)
    if (w) sel.value = w
  }
})
watch([vtab, queue, viewMode], () => { selst.filters.value = { vt: vtab.value, q: queue.value, v: viewMode.value } })
onMounted(() => {
  const f = selst.filters.value
  if (f.vt) vtab.value = f.vt
  if (f.q) queue.value = f.q
  if (f.v === 'table') viewMode.value = 'table'
  // PATCH-02 §3.1 命名视图:overview 三栏 / workflow 表格 / opportunity|position|risk 聚焦
  const vw = String(route.query.view || '')
  if (vw === 'table' || vw === 'workflow') viewMode.value = 'table'
  else if (vw === 'opportunity') { focusCol.value = '机会'; vtab.value = '机会' }
  else if (vw === 'position') { focusCol.value = '持仓'; vtab.value = '持仓' }
  else if (vw === 'risk') { focusCol.value = '风险'; vtab.value = '风险' }
  mixApi.uxPageview('today')   // M5 收敛门槛数据:今日工作 vs 工作台使用量
})
</script>
<style scoped>
.today{height:100%;display:flex;flex-direction:column;background:var(--mix-bg);min-height:0}
.body{flex:1;display:flex;flex-direction:column;gap:8px;padding:8px 12px;min-height:0}
.vtabs{display:none;gap:2px;background:var(--mix-panel);border-radius:6px;padding:2px;align-items:center}
.vt{font-size:11.5px;color:var(--mix-t2);padding:5px 16px;border-radius:5px;cursor:pointer}
.vt.on{background:var(--mix-card2);color:var(--mix-t1);font-weight:700}
.wallbtns{margin-left:auto;display:flex;gap:8px;padding-right:8px}
.wallbtns a{font-size:10px;color:var(--mix-t3);cursor:pointer}
.cols{flex:1;display:flex;gap:8px;min-height:0}
.col{background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.c-opp{width:400px;flex:none}.c-pos{flex:1;min-width:0}.c-risk{width:300px;flex:none}
.chd{display:flex;justify-content:space-between;align-items:baseline;padding:8px 12px 6px}
.chd b{font-size:12px;color:var(--mix-t1)}
.chd i{font-size:9.5px;color:var(--mix-t3);font-style:normal}
.list{flex:1;overflow:auto;min-height:0}
.list.pad{padding:2px 10px 8px;display:flex;flex-direction:column;gap:6px}
.row{display:flex;align-items:center;gap:8px;padding:0 12px;height:44px;border-bottom:1px solid var(--mix-border);cursor:pointer}
.row.tall{flex-direction:column;align-items:stretch;justify-content:center;gap:2px;height:52px}
.row .r1{display:flex;align-items:center;gap:10px}
.row .r2{font-size:9.5px;color:var(--mix-t3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row.sel{background:var(--mix-card2);border-left:2px solid var(--mix-blue)}
.row.bad{background:#F6465D0A}
.row.submitting{opacity:.75}
.sym{font-size:11px;color:var(--mix-t1)}
.ev{font-size:11px;font-weight:700}
.st{font-size:10.5px}
.ddl{font-size:9.5px;color:var(--mix-t3)}
.up{color:var(--mix-green)}.dn{color:var(--mix-red)}.amber{color:var(--mix-accent)}
.fill{flex:1;min-width:0}.fillv{flex:1}
.must{background:#F6465D0D;border:1px solid #F6465D66;border-radius:6px;padding:8px 10px;display:flex;flex-direction:column;gap:3px;cursor:pointer}
.must b{font-size:11px;color:var(--mix-red)}
.qa{display:flex;gap:6px;font-size:9.5px}
.qa i{color:var(--mix-t3);font-style:normal;flex:none;width:64px;font-size:9px}
.qa span{color:var(--mix-t2);line-height:1.35}
.qa a{color:var(--mix-blue);cursor:pointer}
.okline{color:var(--mix-green);font-size:11px;font-weight:700;padding:8px 2px}
.rrow{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px;display:flex;flex-direction:column;gap:1px}
.rrow b{font-size:10px;color:var(--mix-t2)}
.rrow span{font-size:8.5px;color:var(--mix-t3)}
.rrow.warn b{color:#FF8A3D}
.freeze{height:34px;border-radius:6px;background:#F6465D14;border:1px solid #F6465D66;color:var(--mix-red);font-size:11px;font-weight:700;cursor:pointer}
.railrow{display:flex;align-items:center;gap:8px}
.railfill{flex:1;min-width:0}
.vswitch{flex:none;display:flex;background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:2px}
.vswitch a{font-size:10.5px;color:var(--mix-t3);padding:3px 10px;border-radius:4px;cursor:pointer}
.vswitch a.on{background:var(--mix-card2);color:#F0B90B;font-weight:700}
.planbtn{flex:none;font-size:10.5px;padding:5px 10px;border-radius:6px;cursor:pointer;font-weight:700;
  background:#F0B90B14;border:1px solid #F0B90B4D;color:#F0B90B}
.planbtn:hover{border-color:#F0B90B}
.npnote{font-size:10.5px;color:var(--mix-t3);line-height:1.6;margin:4px 0 0}
.trainbtn{flex:none;font-size:10.5px;padding:5px 10px;border-radius:6px;cursor:pointer;
  background:#4A9CFF14;border:1px solid #4A9CFF66;color:var(--mix-blue,#4A9CFF);font-weight:700}
.trainbtn:hover{border-color:#F0B90B;color:#F0B90B}
.dw{display:flex;flex-direction:column;gap:10px}
.dsec i{font-size:9.5px;color:var(--mix-t3);font-style:normal;font-weight:700}
.dsec p{font-size:11.5px;color:var(--mix-t1);margin:3px 0 0;line-height:1.55}
.dsec p.warn{color:#FF8A3D}
.prot{font-size:9px;border-radius:3px;padding:1px 5px;font-weight:700;flex:none}
.prot.WATCH{color:#F0B90B;border:1px solid #F0B90B66}
.prot.NO_ADD{color:#FF8A3D;border:1px solid #FF8A3D88}
.prot.REDUCE_REQUIRED,.prot.EXIT_REQUIRED{color:#F6465D;border:1px solid #F6465D88;background:#F6465D14}
/* §3.1 聚焦视图:query view=opportunity|position|risk 只显示对应栏 */
.cols[data-focus="机会"] .c-pos,.cols[data-focus="机会"] .c-risk{display:none}
.cols[data-focus="持仓"] .c-opp,.cols[data-focus="持仓"] .c-risk{display:none}
.cols[data-focus="风险"] .c-opp,.cols[data-focus="风险"] .c-pos{display:none}
.cols[data-focus="风险"] .c-risk{flex:1}
.cols[data-focus="机会"] .c-opp{flex:1}
.rs{font-size:9px;border:1px solid var(--mix-border);border-radius:3px;padding:1px 5px;margin-right:6px;color:var(--mix-t2)}
.rs.COMPLETED{color:#35b57c;border-color:#35b57c66}
.rs.PENDING{color:#F0B90B;border-color:#F0B90B66}
.rs.EXPIRED{color:#F6465D;border-color:#F6465D66}
.dl{color:var(--mix-blue);cursor:pointer;font-size:10.5px}
.dacts{display:flex;flex-wrap:wrap;gap:6px;padding-top:2px}
.tech{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px;font-size:10px;color:var(--mix-t2);cursor:pointer}
.techb{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px}
.techb p{font-size:9px;color:var(--mix-t3);margin:2px 0;word-break:break-all}
@media (max-width:1360px){
  .vtabs{display:flex}
  .cols[data-vtab='机会'] .c-pos,.cols[data-vtab='机会'] .c-risk{display:none}
  .cols[data-vtab='持仓'] .c-opp,.cols[data-vtab='持仓'] .c-risk{display:none}
  .cols[data-vtab='风险'] .c-opp,.cols[data-vtab='风险'] .c-pos{display:none}
  .c-opp,.c-risk{width:100%}
}
</style>
