<template>
  <!-- V6·DEX/Onchain 实验室(设计帧 F7m9E 1:1):LAB 横幅+实验主表+产品视图+判决;永不出现生产下单按钮 -->
  <div class="v6lab">
    <V6StatusBar :snap="snap" :stale="stale" :can-open="canOpen" :ago="ago"/>
    <div class="labbanner">
      <b class="envtri">控制台环境:PROD ｜ 研究数据域:DEX_LAB ｜ 生产写权限:无</b>
      · 不连接生产资金 · 实验结果不计入客户收益 · 本页永不出现生产下单按钮
      <span class="reach" :class="labUp?'up':'down'">{{ labUp?'D-lab 在线':'D-lab 不可达（生产不受影响）' }}</span>
    </div>
    <div class="body">
      <div class="tabs">
        <span v-for="t in TABS" :key="t" class="tb" :class="{on:tab===t}" @click="tab=t">{{ t }}</span>
      </div>
      <!-- 生命周期阶段条(V6.2 §4.2):服务端真状态,点击=打开该阶段详情/锁定原因——不再是静态装饰 -->
      <div class="flow">
        <span class="flowsel">
          <i v-for="p in PRODUCTS" :key="p" class="sigchip" :class="{on:lcPid===p}" @click="selectProduct(p)">{{ p }}</i>
        </span>
        <template v-if="lcStages.length">
          <span v-for="(s,i) in lcStages" :key="s.stage" class="fs clickable" :class="lcCls(s.status)" @click="openStage(s)">
            {{ s.cn }}<b class="fst">{{ lcStatusCn(s.status) }}</b><em v-if="i<lcStages.length-1">›</em>
          </span>
        </template>
        <span v-else class="t3note">{{ labUp ? '加载生命周期…' : 'D-lab 不可达,生命周期不可用' }}</span>
      </div>
      <!-- 结果与判决页签:研究摘要(research_outbox)+判决全列表——中控台「LAB有新结果」提醒的落点 -->
      <div class="main" v-if="tab==='结果与判决'">
        <div class="tablewrap obwrap">
          <div class="obhd"><b>研究摘要（research_outbox · 单向只读）</b>
            <span class="t3note">LAB 信号只能以摘要形式单向发布;不进 CEX 可执行列表</span></div>
          <div class="oblist">
            <div v-for="o in outbox" :key="o.id" class="obrow clickable" :class="{hl:o.severity==='verdict'}"
                 @click="openDetail(o.project_id, o.title, o.summary)">
              <div class="obr1"><b>{{ o.project_id }}</b><span class="obt">{{ o.title }}</span>
                <i class="obtime">{{ ts(o.created_at) }} · 点击看全文与证据</i></div>
              <div class="obsum pre">{{ o.summary || '（无正文·旧空壳报告,重新生成即有事实正文）' }}</div>
            </div>
            <div v-if="!outbox.length" class="empty">outbox 暂无研究摘要</div>
          </div>
        </div>
        <div class="rcol">
          <div class="card jv" style="flex:1">
            <b>全部判决（点击看详细报告）</b>
            <div v-for="v in verdicts" :key="v.id" class="jrow clickable" :class="{superseded:v.status==='SUPERSEDED'}"
                 @click="openDetail(v.project_id, `${v.project_id} 判决:${verdictCn(v.verdict)}`, v.reason)">
              <span class="jp">{{ v.project_id }} <i class="obtime">{{ ts(v.created_at) }}</i>
                <i v-if="v.status==='SUPERSEDED'" class="suptag">已撤回{{ v.legacy_verdict?('(原:'+v.legacy_verdict+')'):'' }}</i></span>
              <span class="jv2" :class="verdictCls(v.verdict)">{{ verdictCn(v.verdict) }}</span>
              <span class="jr">{{ v.status==='SUPERSEDED' ? ('撤回原因:'+(v.supersede_reason||'')+' ｜ ') : '' }}{{ v.reason }}</span>
            </div>
            <div v-if="!verdicts.length" class="empty sm">暂无判决</div>
          </div>
        </div>
      </div>
      <!-- 运行记录页签 -->
      <div class="main" v-else-if="tab==='运行记录'">
        <div class="tablewrap obwrap">
          <div class="obhd"><b>实验运行记录</b><span class="t3note">R1 实时样本来自 D-lab 本机 xv 采样库</span></div>
          <div class="oblist">
            <div v-for="r in labRuns" :key="r.run_id" class="obrow">
              <div class="obr1"><b>#{{ r.run_id }} · {{ r.project_id }}</b><span class="obt">{{ r.kind }}</span>
                <i class="obtime">{{ r.state }}</i></div>
              <div class="obsum">开始 {{ ts(r.started_at) }}{{ r.ended_at ? ' · 结束 '+ts(r.ended_at) : ' · 运行中' }}</div>
            </div>
            <div v-if="!labRuns.length" class="empty">暂无运行记录（在实验总览对项目执行 扫描/回放/影子 后生成）</div>
          </div>
        </div>
      </div>
      <!-- 扫描与观察:lab_signal 逐轮明细(扫描器 worker 真数据) -->
      <div class="main" v-else-if="tab==='扫描与观察'">
        <div class="tablewrap obwrap">
          <div class="obhd"><b>扫描信号（lab_signal · 5 分钟/轮）</b>
            <span class="sigchips">
              <i v-for="p in ['','D1','D2','D4']" :key="p" class="sigchip" :class="{on:sigFilter===p}"
                 @click="sigFilter=p; loadSignals()">{{ p||'全部' }}</i>
            </span>
            <span class="t3note">初步信号=原始观察,不代表可成交;可执行净收益待计算(需目标金额真实报价)</span></div>
          <div class="oblist">
            <div v-for="s in sigRows" :key="s.id" class="obrow clickable" @click="sigOpen=sigOpen===s.id?0:s.id">
              <div class="obr1"><b>{{ s.project_id }}</b>
                <span class="obt" :class="(s.payload?.best_bps||s.payload?.net_best_bps||0)>0?'amber':'t2'">
                  初步最优 {{ fmt1(s.payload?.best_bps ?? s.payload?.net_best_bps) }} bps</span>
                <span class="sigkind" v-if="s.payload?.signal_kind">{{ kindCn(s.payload.signal_kind) }}</span>
                <span class="t3note">中位 {{ fmt1(s.payload?.median_bps) }} · 参考成本 {{ s.payload?.cost_bps }}bps · 净收益:待计算 · {{ (s.payload?.signals||[]).length }} 标的</span>
                <i class="obtime">{{ ts(s.ts) }} · 点击展开</i></div>
              <div v-if="sigOpen===s.id" class="sigdetail">
                <div v-for="(g,i) in (s.payload?.signals||[])" :key="i" class="sigline">
                  <b>{{ g.asset }}</b>
                  <span v-if="g.discount_bps!=null" :class="g.discount_bps>0?'amber':'t3'">{{ g.discount_bps>=0 ? '折价 '+fmt1(g.discount_bps) : '溢价 '+fmt1(-g.discount_bps) }} bps</span>
                  <span v-else-if="g.spread_bps!=null" :class="g.spread_bps>0?'amber':'t3'">{{ s.payload?.signal_kind==='IMPLIED_YIELD_SPREAD' ? '隐含利差(年化) ' : s.payload?.signal_kind==='VARIABLE_RATE_MONITOR' ? '浮动差(年化) ' : '利差 ' }}{{ fmt1(g.spread_bps) }} bps</span>
                  <span v-else-if="g.rate_source==='MISSING_ONCHAIN_RATE'" class="redtxt">缺链上赎回价·不给折价</span>
                  <span class="t3note">{{ g.best ? g.best+' vs '+g.worst
                    : g.implied_apy_pct!=null ? '隐含 '+g.implied_apy_pct+'% / 底层 '+g.underlying_apy_pct+'%'+(g.days_to_maturity!=null?' · 距到期 '+g.days_to_maturity+'d':'')
                    : g.redemption_rate!=null ? '赎回价 '+g.redemption_rate+'('+(g.rate_source==='onchain'?'链上':'协议1:1')+') · 市价比 '+g.market_ratio
                    : (g.kind||'') }}</span>
                </div>
              </div>
            </div>
            <div v-if="!sigRows.length" class="empty">暂无信号（扫描器每 5 分钟一轮;确认项目已「开始扫描」）</div>
          </div>
        </div>
      </div>
      <div class="main" v-else-if="tab!=='实验总览'">
        <div class="tablewrap obwrap"><div class="empty">「{{ tab }}」明细面板待接 D-lab 数据流——当前请在 实验总览/扫描与观察/结果与判决/运行记录 查看;该页签不显示假数据</div></div>
      </div>
      <div class="main" v-else>
        <div class="tablewrap">
          <div class="thead">
            <span class="lc" style="width:128px">编号/项目</span><span class="lc" style="width:104px">链/协议/池</span>
            <span class="lc" style="width:70px">当前阶段</span><span class="lc" style="width:56px">样本量</span>
            <span class="lc" style="width:118px" title="原始观察信号,不代表可成交;可执行净收益待计算">初步信号(原始口径)</span>
            <span class="lc" style="width:56px">存活</span>
            <span class="lc" style="width:64px" title="typed证据覆盖:已具备/必需">证据闸</span>
            <span class="lc" style="width:66px">新鲜度</span>
            <span class="lc" style="width:96px">当前结论</span><span class="lact">下一步</span>
          </div>
          <div class="tbody">
            <div v-for="p in projects" :key="p.project_id" class="trow" :class="{sel:sel?.project_id===p.project_id}" @click="pickRow(p)">
              <span class="lc t1b" style="width:128px" :title="p.title">{{ p.project_id }} · {{ p.title }}</span>
              <span class="lc t2" style="width:104px">{{ p.chain_protocol || 'N/A' }}</span>
              <span class="lc" style="width:70px" :class="stageCls(p.stage)">{{ stageCn(p.stage) }}</span>
              <span class="lc t2" style="width:56px">{{ sampleOf(p) }}</span>
              <span class="lc" style="width:118px" :class="resultCls(p)" :title="p.kind_note">{{ resultOf(p) }}</span>
              <span class="lc t3" style="width:56px">{{ p.runs?p.runs+' 轮':'—' }}</span>
              <span class="lc" style="width:64px" :class="evCls(p)">{{ p.evidence_gate?.coverage || '—' }}</span>
              <span class="lc t3" style="width:66px">{{ freshOf(p) }}</span>
              <span class="lc" style="width:96px" :class="verdictCls(p.latest_verdict)" :title="p.latest_verdict_reason">{{ verdictOf(p) }}</span>
              <!-- 操作列定宽最右,永不被挤出(遮挡课);判决入口补齐(命令白名单此前UI空转) -->
              <span class="lact">
                <button class="ob" @click.stop="openEvidence(p)">证据</button>
                <button class="ob" @click.stop="report(p)">报告</button>
                <button class="ob" @click.stop="openVerdict(p)">判决</button>
              </span>
            </div>
            <div v-if="!projects.length" class="empty">{{ labUp?'暂无实验项目':'D-lab 不可达,无法读取实验项目（生产不受影响）' }}</div>
          </div>
          <div class="tfoot">保留观察/影子测试/停止测试 ｜ 允许动作仅：开始/停止扫描 · 回放 · 标注 · 导出报告 · 生成 canary/生产化提案 ｜ HL-CEX 生产 carry 在 C2，不入 LAB 收益榜</div>
        </div>
        <!-- 右列:产品视图+最近判决 -->
        <div class="rcol">
          <div class="card pv">
            <b>产品视图</b>
            <div v-for="pd in PRODUCTS" :key="pd" class="pline">
              <span class="pn">{{ pd }}</span>
              <span class="ps" :class="prodStageCls(pd)">{{ prodStage(pd) }}</span>
            </div>
          </div>
          <div class="card jv">
            <b>最近判决</b>
            <div v-for="v in verdicts.slice(0,6)" :key="v.id" class="jrow">
              <span class="jp">{{ v.project_id }}</span>
              <span class="jv2" :class="verdictCls(v.verdict)">{{ verdictCn(v.verdict) }}</span>
              <span class="jr">{{ v.reason }}</span>
            </div>
            <div v-if="!verdicts.length" class="empty sm">暂无判决</div>
            <div class="fillv"></div>
            <p class="jnote">实验信号不入 CEX 可执行列表；机会墙只收到一条「LAB 有新结果」提醒</p>
          </div>
        </div>
      </div>
    </div>
    <!-- 判决弹窗(V6.2:SHADOW 已从判决移除——它是阶段;证据闸在 D-lab 服务端硬拦) -->
    <el-dialog v-model="vd.open" :title="`判决 · ${vd.pid}`" width="560px">
      <el-radio-group v-model="vd.verdict">
        <el-radio-button value="KEEP_MEASURING">保留研究</el-radio-button>
        <el-radio-button value="ADVANCE_REVIEW">提交评审</el-radio-button>
        <el-radio-button value="KILL">停止研究</el-radio-button>
        <el-radio-button value="INSUFFICIENT_EVIDENCE">证据不足</el-radio-button>
        <el-radio-button value="RETEST_APPROVED">允许重测</el-radio-button>
        <el-radio-button value="GRADUATE_PROPOSAL">生产化提案</el-radio-button>
      </el-radio-group>
      <div class="t3note" style="margin-top:8px">
        保留研究/提交评审/生产化提案须过证据闸(缺必需证据类型或轮次运行中=服务端 409 拒绝);
        停止研究/证据不足/允许重测随时可登记。「保留研究」只表示继续验证,不表示可交易。
      </div>
      <div v-if="vd.gateErr" class="gateerr">{{ vd.gateErr }}</div>
      <el-input v-model="vd.reason" type="textarea" :rows="4" style="margin-top:10px"
                placeholder="判决理由(必填,进证据链;生产化提案只生成提案,不能自动切PROD)"/>
      <template #footer>
        <el-button @click="vd.open=false">取消</el-button>
        <el-button type="warning" @click="submitVerdict">登记判决</el-button>
      </template>
    </el-dialog>
    <!-- 证据登记弹窗(annotate 带 evidence_type:typed 证据进闸,自由标注不计闸) -->
    <el-dialog v-model="ed.open" :title="`登记证据 · ${ed.pid}`" width="560px">
      <el-form label-width="86px" size="small">
        <el-form-item label="证据类型">
          <el-select v-model="ed.etype" style="width:100%">
            <el-option v-for="t in ed.types" :key="t" :value="t" :label="`${etCn(t)}(${t})`"/>
            <el-option value="" label="(自由标注·不计入证据闸)"/>
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="ed.title" maxlength="120" placeholder="一句话说清这条证据证明什么"/></el-form-item>
        <el-form-item label="来源"><el-input v-model="ed.source" maxlength="120" placeholder="链上RPC/官方文档/真实报价截图路径…(转载同一来源不算独立证据)"/></el-form-item>
        <el-form-item label="正文"><el-input v-model="ed.body" type="textarea" :rows="5" maxlength="2000"
          placeholder="事实本体:数值/区块号/合约地址/报价金额与时间…(进不可变证据链,判决快照将引用)"/></el-form-item>
      </el-form>
      <div class="t3note">当前覆盖:{{ ed.cov }}｜缺:{{ ed.missing.length ? ed.missing.map(etCn).join(' / ') : '无' }}</div>
      <template #footer>
        <el-button @click="ed.open=false">取消</el-button>
        <el-button type="warning" @click="submitEvidence">登记证据</el-button>
      </template>
    </el-dialog>
    <!-- 阶段详情抽屉(阶段条点击落点:状态/锁定原因/完成条件/该阶段数据) -->
    <el-drawer v-model="stg.open" :title="stg.s ? `${lcPid} · ${stg.s.cn} 阶段` : ''" size="440px">
      <div class="dwrap" v-if="stg.s">
        <div class="dsec"><b>状态</b><p :class="lcCls(stg.s.status)">{{ lcStatusCn(stg.s.status) }}</p></div>
        <div class="dsec" v-if="stg.s.blocking_reasons?.length"><b>未解锁原因</b>
          <p v-for="(r,i) in stg.s.blocking_reasons" :key="i" class="pre">· {{ r }}</p></div>
        <div class="dsec" v-if="stg.s.completion_condition"><b>完成/开放条件</b><p>{{ stg.s.completion_condition }}</p></div>
        <div class="dsec" v-if="stg.s.next_action"><b>下一步动作</b><p>{{ nextActionCn(stg.s.next_action) }}</p></div>
        <div class="dsec" v-if="stg.s.stage==='MEASURE'"><b>本项目轮次</b>
          <div v-for="r in labRuns.filter(x=>x.project_id===lcPid).slice(0,8)" :key="r.run_id" class="dev">
            <div class="devt">#{{ r.run_id }} {{ r.kind }} · {{ r.state }}</div>
            <p class="pre">{{ r.note || ('样本 '+(r.samples||0)) }}</p>
          </div>
          <p v-if="!labRuns.filter(x=>x.project_id===lcPid).length" class="t3note">尚无轮次</p>
        </div>
        <div class="dsec" v-if="stg.s.stage==='REVIEW'"><b>证据闸</b>
          <p>覆盖:{{ stg.s.data?.evidence_gate?.coverage }}
            <template v-if="stg.s.data?.evidence_gate?.missing?.length">
              · 缺:{{ stg.s.data.evidence_gate.missing.join(' / ') }}</template></p>
          <p class="t3note">证据经「标注」命令带 evidence_type 登记;转载同一来源不算独立证据</p>
        </div>
      </div>
    </el-drawer>
    <!-- 详情抽屉:摘要/判决全文 + 该项目全部证据(lab_evidence) -->
    <el-drawer v-model="detail.open" :title="detail.title" size="520px">
      <div class="dwrap">
        <div class="dsec"><b>正文</b><p class="pre">{{ detail.body || '（无正文）' }}</p></div>
        <div class="dsec"><b>证据条目（{{ detail.evidence.length }}）</b>
          <div v-for="e in detail.evidence" :key="e.id" class="dev">
            <div class="devt">{{ e.kind }} · {{ e.title }} <i class="obtime">{{ ts(e.created_at) }}</i></div>
            <p class="pre">{{ e.body }}</p>
          </div>
          <p v-if="!detail.evidence.length" class="t3note">该项目暂无证据条目</p>
        </div>
      </div>
    </el-drawer>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'
import { useV6Snapshot } from '../../composables/useV6'
import V6StatusBar from '../../components/V6StatusBar.vue'

const { snap, stale, canOpen, ago } = useV6Snapshot()
const tab = ref('实验总览')
const sel = ref(null)
const labUp = ref(false)
const projects = ref([])
const verdicts = ref([])
const runsMeta = ref(null)

const TABS = ['实验总览', '扫描与观察', '回放与成本', '结果与判决', '链路健康', '运行记录']
const outbox = ref([])
const labRuns = ref([])
// 详情抽屉:点击摘要/判决 → 全文+项目证据
const detail = ref({ open: false, title: '', body: '', evidence: [] })
// 扫描信号(扫描与观察页签)
const sigRows = ref([]); const sigFilter = ref(''); const sigOpen = ref(0)
async function loadSignals() {
  try { const r = await mixApi.v6LabSignals(sigFilter.value ? { project: sigFilter.value } : {}); sigRows.value = r?.data || [] }
  catch (e) { sigRows.value = [] }
}
watch(tab, t => { if (t === '扫描与观察') loadSignals() })
async function openDetail(pid, title, body) {
  detail.value = { open: true, title, body, evidence: [] }
  try {
    const r = await mixApi.v6LabEvidence({ project: pid })
    detail.value.evidence = r?.data || []
  } catch (e) { /* LAB不可达=证据留空 */ }
}
function ts(t) { if (!t) return ''; const d = new Date(t * 1000); return `${d.getMonth()+1}-${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}` }
const PRODUCTS = ['R1', 'D1', 'D2', 'D3', 'D4']
// ── 生命周期阶段条(V6.2 §4.2):服务端真状态,URL query 同步(product/stage) ──
const route = useRoute(); const router = useRouter()
const lcPid = ref(''); const lcStages = ref([])
const stg = ref({ open: false, s: null })
async function loadLifecycle() {
  if (!lcPid.value) { lcStages.value = []; return }
  try {
    const r = await mixApi.v6LabLifecycle(lcPid.value)
    lcStages.value = r?.data?.stages || []
  } catch (e) { lcStages.value = [] }
}
function selectProduct(p) {
  lcPid.value = p
  router.replace({ query: { ...route.query, product: p } })
  loadLifecycle()
}
function pickRow(p) { sel.value = p; if (p.project_id !== lcPid.value) selectProduct(p.project_id) }
function openStage(s) {
  stg.value = { open: true, s }
  router.replace({ query: { ...route.query, product: lcPid.value, stage: s.stage } })
}
function lcStatusCn(st) { return ({ COMPLETED: '已完成', CURRENT: '进行中', AVAILABLE: '可开始', LOCKED: '未解锁', FAILED: '失败', NOT_APPLICABLE: '不适用' })[st] || st }
function lcCls(st) { return ({ COMPLETED: 'g', CURRENT: 'cur', AVAILABLE: 'b', LOCKED: 'n', FAILED: 'redbg', NOT_APPLICABLE: 'na' })[st] || 'n' }
function nextActionCn(a) {
  return ({ scan_start: '开始扫描(登记 MEASURE 轮次,worker 每5分钟采样)', scan_stop: '停止扫描(轮次转 DONE,判决只消费已完成轮次)',
    verdict: '登记判决(证据闸服务端硬拦)', 'verdict:RETEST_APPROVED': '先登记「允许重测」判决,再重新采样' })[a] || a
}
function fmt1(v) { return v == null ? '—' : Number(v).toFixed(1) }
function kindCn(k) { return ({ RAW_DISCOUNT: '原始折/溢价', IMPLIED_YIELD_SPREAD: '隐含收益率差(年化)', VARIABLE_RATE_MONITOR: '浮动利率观察(年化)', FUNDING_GAP_SAMPLE: '费差样本' })[k] || (k || '') }

function stageCn(s) { return ({ IDEA: '想法', MEASURE: '测量', REPLAY: '回放', SHADOW: '影子测试', CANARY: 'Canary', KILL_CANDIDATE: '待停', REVIEW: '判决' })[s] || s }
function stageCls(s) { return ['SHADOW'].includes(s) ? 'blue' : (['KILL_CANDIDATE'].includes(s) ? 'redtxt' : 'green') }
// V6.2 判决枚举(SHADOW 已移除=阶段);旧值兼容显示
function verdictCn(v) {
  return ({ KEEP_MEASURING: '保留研究', ADVANCE_REVIEW: '提交评审', KILL: '停止研究',
    GRADUATE_PROPOSAL: '生产化提案', INSUFFICIENT_EVIDENCE: '证据不足', RETEST_APPROVED: '允许重测',
    KEEP: '保留研究(旧)', SHADOW: '保留研究(旧·影子)', null: '—' })[v] || (v || '—')
}
function verdictCls(v) { return v === 'KILL' ? 'redtxt' : (v === 'GRADUATE_PROPOSAL' ? 'green' : (v === 'INSUFFICIENT_EVIDENCE' ? 'amber' : 't3')) }
// 结论列:无判决时按证据闸如实显示「待取证」而不是空
function verdictOf(p) {
  if (p.latest_verdict) {
    const base = verdictCn(p.latest_verdict)
    return (p.latest_verdict === 'KILL' && p.retest_at) ? base + '·重测已批' : base
  }
  const g = p.evidence_gate
  return (g && g.required?.length && !g.gate_pass) ? '待取证' : '待判决'
}
function evCls(p) { const g = p.evidence_gate; if (!g || !g.required?.length) return 't3'; return g.gate_pass ? 'green' : 'redtxt' }
// 颜色纪律(§6.2):绿=证据闸通过且为正;原始正信号=中性黄;其余灰
function resultCls(p) {
  const v = p.latest_result_bps
  if (v == null) return 't2'
  if (p.evidence_gate?.gate_pass && v > 0) return 'green'
  return v > 0 ? 'amber' : 't2'
}
function sampleOf(p) {
  if (p.project_id === 'R1' && runsMeta.value?.r1_live)
    return (runsMeta.value.r1_live.samples_24h || runsMeta.value.r1_live.total_samples || 0) + ''
  return p.samples_total > 0 ? String(p.samples_total) : '—'
}
function freshOf(p) {
  if (p.project_id === 'R1' && runsMeta.value?.r1_live) return '实时'
  if (!p.last_signal_ts) return '—'
  const age = Math.floor(Date.now() / 1000 - p.last_signal_ts)
  return age < 600 ? `${Math.max(1, Math.floor(age/60))}m前` : age < 86400 ? `${Math.floor(age/3600)}h前` : '过期'
}
// 初步信号列(§6.1 口径拆分):按 signal_kind 标注;D1 负数=溢价;净收益一律待计算
function resultOf(p) {
  const v = p.latest_result_bps
  if (v == null) return '待采样'
  const k = p.signal_kind
  if (k === 'RAW_DISCOUNT') return v >= 0 ? `折价 ${fmt1(v)} bps` : `溢价 ${fmt1(-v)} bps`
  if (k === 'IMPLIED_YIELD_SPREAD') return `隐含差 ${fmt1(v)} bps·年化`
  if (k === 'VARIABLE_RATE_MONITOR') return `浮动差 ${fmt1(v)} bps·年化`
  return `${fmt1(v)} bps`
}
function prodStage(pd) { const p = projects.value.find(x => x.project_id === pd); return p ? stageCn(p.stage) : 'N/A' }
function prodStageCls(pd) { const p = projects.value.find(x => x.project_id === pd); return p ? stageCls(p.stage) : 't3' }
async function report(p) {
  try {
    await mixApi.v6LabCommand({ command: 'report', project_id: p.project_id, environment: 'DEX_LAB' })
    ElMessage.success(`${p.project_id} 报告已生成(事实合成正文)→ 结果与判决`)
    load()
  } catch (e) { ElMessage.error(e?.detail || 'LAB 不可达') }
}
// 证据登记入口(annotate 带 evidence_type;typed 证据计入闸,operator 权限)
const ET_CN = { CONTRACT_IDENTITY: '合约身份', EXCHANGE_RATE: '链上兑换率', REDEEM_STATUS: '赎回状态',
  TARGET_QUOTE: '目标金额真实报价', MATURITY_ONCHAIN: '链上到期', REDEMPTION_MODEL: '兑付模型',
  CEX_DEPOSIT_OPEN: 'CEX充值开放', CHAIN_CONTRACT_MAPPING: '链/合约映射', TRANSFER_TIMING: '到账时间分布',
  HEDGE_DEPTH: '对冲深度', FIXED_RATE_LOCK: '可锁定固定利率', TERM_MATCH: '期限匹配',
  CAPACITY: '真实额度', COLLATERAL_COST: '抵押与清算成本' }
function etCn(t) { return ET_CN[t] || t || '自由标注' }
const ed = ref({ open: false, pid: '', etype: '', types: [], title: '', source: '', body: '', cov: '', missing: [] })
function openEvidence(p) {
  const g = p.evidence_gate || {}
  ed.value = { open: true, pid: p.project_id, types: g.required || [], etype: (g.missing || [])[0] || (g.required || [])[0] || '',
    title: '', source: '', body: '', cov: g.coverage || '—', missing: g.missing || [] }
}
async function submitEvidence() {
  if (!ed.value.title.trim() || !ed.value.body.trim()) { ElMessage.warning('标题与正文必填(进不可变证据链)'); return }
  try {
    await mixApi.v6LabCommand({ command: 'annotate', project_id: ed.value.pid, environment: 'DEX_LAB',
      evidence_type: ed.value.etype, title: ed.value.title, source: ed.value.source, body: ed.value.body })
    ElMessage.success(ed.value.etype ? `已登记 typed 证据:${etCn(ed.value.etype)}` : '已登记自由标注')
    ed.value.open = false; load(); loadLifecycle()
  } catch (e) { ElMessage.error(typeof e?.detail === 'string' ? e.detail : JSON.stringify(e?.detail || '失败')) }
}
// 判决入口:V6.2 新枚举 + 服务端证据闸(409 结构化拒绝原样展示,绝不显示假成功)
const vd = ref({ open: false, pid: '', verdict: 'KEEP_MEASURING', reason: '', gateErr: '' })
function openVerdict(p) { vd.value = { open: true, pid: p.project_id, verdict: 'KEEP_MEASURING', reason: '', gateErr: '' } }
async function submitVerdict() {
  if (!vd.value.reason.trim()) { ElMessage.warning('判决理由必填(进证据链)'); return }
  vd.value.gateErr = ''
  try {
    await mixApi.v6LabCommand({ command: 'verdict', project_id: vd.value.pid, environment: 'DEX_LAB',
      verdict: vd.value.verdict, reason: vd.value.reason })
    ElMessage.success(`${vd.value.pid} 判决已登记并发布摘要`)
    vd.value.open = false; load(); loadLifecycle()
  } catch (e) {
    const d = e?.detail
    if (d && typeof d === 'object') {
      const miss = (d.missing_evidence_types || []).join(' / ')
      vd.value.gateErr = `被拒(${d.code || '409'}):` + (d.blocking_reasons || []).join('；') + (miss ? `｜缺证据类型:${miss}` : '')
    } else {
      vd.value.gateErr = String(d || '失败')
    }
    ElMessage.error('判决被服务端拒绝,原因见弹窗')
  }
}
async function load() {
  try {
    const h = await mixApi.v6LabHealth(); labUp.value = !!h?.lab_reachable
    const pj = await mixApi.v6LabProjects(); projects.value = pj?.data || []
    const vd = await mixApi.v6LabVerdicts(); verdicts.value = vd?.data || []
    const rn = await mixApi.v6LabRuns(); runsMeta.value = rn?.data || null
    labRuns.value = rn?.data?.runs || []
    const ob = await mixApi.v6LabOutbox(); outbox.value = ob?.data || []
  } catch (e) { labUp.value = false }
}
onMounted(async () => {
  await load()
  // 中控台「LAB有新结果」提醒的落点:?focus=outbox 直达 结果与判决
  const q = new URLSearchParams(location.search)
  if (q.get('focus') === 'outbox') tab.value = '结果与判决'
  // §4.2 URL 恢复:?product=&stage= → 选中项目+打开阶段详情
  const prod = q.get('product')
  lcPid.value = (prod && PRODUCTS.includes(prod)) ? prod : (projects.value[0]?.project_id || '')
  if (lcPid.value) {
    await loadLifecycle()
    const st = q.get('stage')
    const hit = lcStages.value.find(s => s.stage === st)
    if (hit) stg.value = { open: true, s: hit }
  }
})
</script>
<style scoped>
.v6lab{height:100%;display:flex;flex-direction:column;background:var(--mix-bg);min-height:0}
.labbanner{background:#4A9CFF14;border-bottom:1px solid #4A9CFF66;color:var(--mix-blue);font-size:11px;font-weight:700;padding:6px 14px;display:flex;align-items:center;gap:8px}
.reach{margin-left:auto;font-size:10px;padding:2px 8px;border-radius:4px}
.reach.up{background:#0ECB8114;color:var(--mix-green)}
.reach.down{background:#F6465D14;color:var(--mix-red)}
.body{flex:1;display:flex;flex-direction:column;gap:8px;padding:8px 12px;min-height:0}
.tabs{display:flex;gap:2px;background:var(--mix-panel);border-radius:6px;padding:2px;align-self:flex-start}
.tb{font-size:11.5px;color:var(--mix-t2);padding:4px 13px;border-radius:5px;cursor:pointer}
.tb.on{background:var(--mix-card2);color:var(--mix-t1);font-weight:700}
.flow{display:flex;gap:3px;align-items:center;flex-wrap:wrap}
.fs{flex:1 1 120px;min-width:0;height:30px;display:flex;align-items:center;justify-content:center;gap:6px;border-radius:6px;font-size:10px;font-weight:700;border:1px solid var(--mix-border);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 6px}
.fs.g{background:#0ECB810F;color:var(--mix-green)}
.fs.b{background:#4A9CFF14;color:var(--mix-blue);border-color:#4A9CFF66}
.fs.n{background:var(--mix-panel);color:var(--mix-t3)}
.fs.cur{background:#F0B90B1F;color:var(--mix-accent);border-color:#F0B90B4D}
.fs.redbg{background:#F6465D14;color:var(--mix-red);border-color:#F6465D66}
.fs.na{background:var(--mix-panel);color:var(--mix-t3);opacity:.45}
.fs em{font-style:normal;color:var(--mix-t3);margin-left:4px}
.fst{font-size:8.5px;font-weight:400;opacity:.85;margin-left:2px}
.flowsel{display:flex;gap:4px;align-items:center;margin-right:6px;flex:none}
.envtri{color:var(--mix-t1)}
.gateerr{margin-top:8px;font-size:11px;color:var(--mix-red);background:#F6465D0D;border:1px solid #F6465D66;border-radius:6px;padding:6px 10px;line-height:1.5;white-space:pre-wrap}
.suptag{font-style:normal;font-size:8.5px;color:var(--mix-red);border:1px solid #F6465D66;border-radius:3px;padding:0 4px;margin-left:6px}
.jrow.superseded{opacity:.55}
.amber{color:var(--mix-accent)}
.sigkind{font-size:9px;color:var(--mix-blue);border:1px solid #4A9CFF66;border-radius:3px;padding:0 5px}
.main{flex:1;display:flex;gap:8px;min-height:0;min-width:0}
.tablewrap{flex:1;min-width:0;background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;display:flex;flex-direction:column;overflow:hidden}
.thead{display:flex;height:24px;background:var(--mix-panel);border-bottom:1px solid var(--mix-border);flex:none;min-width:0}
.thead span{font-size:8.5px;font-weight:700;color:var(--mix-t3);padding:0 7px;white-space:nowrap;overflow:hidden;display:flex;align-items:center;min-width:0;flex-shrink:1}
.tbody{flex:1;overflow:auto;min-height:0}
.trow{display:flex;align-items:center;height:32px;border-bottom:1px solid var(--mix-border);cursor:pointer;min-width:0}
.trow span{font-size:9.5px;padding:0 7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex-shrink:1}
/* 数据列显式可收缩(inline width 只是 flex-basis);操作列定宽最右永不被挤出 */
.lc{flex-shrink:1!important;min-width:36px!important}
.lact{flex:0 0 150px!important;display:flex;gap:4px;align-items:center;justify-content:flex-end;padding:0 7px;overflow:visible!important}
/* 研究摘要/运行记录列表(结果与判决页签=中控台LAB提醒落点) */
.obwrap{padding:0}
.obhd{display:flex;align-items:baseline;gap:10px;padding:10px 14px;border-bottom:1px solid var(--mix-border)}
.obhd b{font-size:12.5px;color:var(--mix-t1)}
.t3note{font-size:9.5px;color:var(--mix-t3)}
.oblist{flex:1;overflow:auto;min-height:0;padding:6px 10px;display:flex;flex-direction:column;gap:6px}
.obrow{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:8px 12px}
.obrow.hl{border-color:#4A9CFF66;background:#4A9CFF0D}
.obr1{display:flex;align-items:center;gap:8px}
.obr1 b{font-size:11.5px;color:var(--mix-blue)}
.obt{font-size:11px;color:var(--mix-t1);font-weight:700}
.obtime{font-size:9px;color:var(--mix-t3);font-style:normal;margin-left:auto}
.obsum{font-size:10.5px;color:var(--mix-t2);margin-top:4px;line-height:1.5;word-break:break-all}
.clickable{cursor:pointer;transition:border-color .12s}
.clickable:hover{border-color:#F0B90B66}
.pre{white-space:pre-wrap}
.dwrap{display:flex;flex-direction:column;gap:14px}
.dsec b{font-size:12px;color:var(--mix-t1)}
.dsec p{font-size:12px;color:var(--mix-t2);line-height:1.65;margin:6px 0 0}
.dev{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:8px 12px;margin-top:8px}
.devt{font-size:11px;font-weight:700;color:var(--mix-blue);display:flex;gap:8px;align-items:center}
.sigchips{display:flex;gap:4px}
.sigchip{font-size:10px;font-style:normal;padding:2px 9px;border-radius:5px;border:1px solid var(--mix-border);color:var(--mix-t2);cursor:pointer}
.sigchip.on{color:var(--mix-accent);background:#F0B90B1F;border-color:#F0B90B4D}
.sigdetail{margin-top:6px;border-top:1px solid var(--mix-border);padding-top:6px;display:flex;flex-direction:column;gap:3px}
.sigline{display:flex;gap:10px;font-size:10.5px;align-items:baseline}
.sigline b{color:var(--mix-t1);min-width:150px}
.green{color:var(--mix-green)}.redtxt{color:var(--mix-red)}
.trow.sel{background:var(--mix-card2)}
.tfoot{font-size:8.5px;color:var(--mix-t3);padding:5px 10px;border-top:1px solid var(--mix-border)}
.rcol{width:400px;flex:none;display:flex;flex-direction:column;gap:8px;min-height:0}
.card{background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;padding:8px 12px}
.card b{font-size:11.5px;color:var(--mix-t1)}
.pv{flex:none}
.pline{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--mix-border)}
.pn{font-size:11px;color:var(--mix-t2);font-weight:700}
.ps{font-size:10px}
.jv{flex:1;display:flex;flex-direction:column;gap:6px;min-height:0;overflow:auto}
.jrow{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 9px;display:flex;flex-direction:column;gap:2px}
.jp{font-size:10px;font-weight:700;color:var(--mix-t1)}
.jv2{font-size:10px}
.jr{font-size:9px;color:var(--mix-t3);line-height:1.4}
.jnote{font-size:8.5px;color:var(--mix-t3);line-height:1.45;margin:0}
.ob{font-size:9px;font-weight:700;padding:2px 8px;border-radius:4px;border:1px solid var(--mix-border);background:var(--mix-card2);color:var(--mix-t1);cursor:pointer}
.empty{padding:24px;text-align:center;color:var(--mix-t3);font-size:11px}.empty.sm{padding:10px;font-size:10px}
.fill{flex:1;min-width:0}.fillv{flex:1}
.t1b{color:var(--mix-t1);font-weight:700}.t2{color:var(--mix-t2)}.t3{color:var(--mix-t3)}
.green{color:var(--mix-green)}.blue{color:var(--mix-blue)}.redtxt{color:var(--mix-red)}
@media (max-width:1600px){ .rcol{width:320px} }
@media (max-width:1200px){ .rcol{width:280px} }
@media (max-width:960px){ .main{flex-direction:column} .rcol{width:100%} }
</style>
