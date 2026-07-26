<template>
  <!-- V6·中控台三分屏(设计帧 joknS 1:1):三墙=同一 control_snapshot 的三个投影,同 generation -->
  <div class="v6con">
    <V6StatusBar :snap="snap" :stale="stale" :can-open="canOpen" :ago="ago" :operator="opName"/>
    <div class="body">
      <!-- 顶行:聚焦 | 联动注 | 快捷 -->
      <div class="toprow">
        <div class="focus">
          <span v-for="f in ['屏1·机会墙','屏2·持仓墙','屏3·风控墙']" :key="f"
                class="fitem" :class="{on:focus===f}" @click="focus=focus===f?'':f">{{ f }}</span>
        </div>
        <div class="linknote" v-if="selected">
          <FIcon name="dots" :size="12"/> 三栏联动选中：{{ selected }} · 详情走右侧抽屉，不丢上下文
        </div>
        <div class="quick">
          <button class="qb red" :disabled="pausing" @click="pauseNewRisk"><FIcon name="pause" :size="12"/> 暂停新增</button>
          <button class="qb gold" @click="$router.push('/mix/maintenance')"><FIcon name="tool" :size="12"/> 开始维护</button>
          <button class="qb red" @click="openTopRisk"><FIcon name="alert" :size="12"/> 打开最高风险</button>
        </div>
      </div>
      <!-- 三墙 -->
      <div class="walls">
        <!-- 屏1·机会墙 462 -->
        <div class="wall w1" v-show="!focus || focus==='屏1·机会墙'">
          <div class="whd"><b>机会墙</b><i>候选 {{ oppTotal }} → 过闸 {{ opps.length }}</i></div>
          <div class="filts">
            <span v-for="f in OPP_FILTS" :key="f" class="fc" :class="{on:oppFilt===f}" @click="oppFilt=f">{{ f }}</span>
          </div>
          <div class="labbar" v-if="labNote"><FIcon name="flask" :size="12"/> {{ labNote }} → <a @click="$router.push({path:'/mix/lab',query:{focus:'outbox'}})">实验室·结果与判决</a>
            <span class="labdismiss" title="标记已读(有新摘要会再次提醒)" @click="dismissLab"><FIcon name="x" :size="11"/></span></div>
          <div class="olist">
            <div v-for="o in oppsFiltered" :key="o.work_item_id" class="orow"
                 :class="{sel:selected===o.symbol}" @click="selected=o.symbol">
              <div class="or1">
                <span class="sym"><b style="color:var(--mix-gold,#F0B90B);font-weight:800">{{ o.symbol }}</b> · <i :class="'px-'+String(o.strategy_code||'').split('.')[0].toLowerCase()" style="font-style:normal">{{ o.strategy_code }}</i></span>
                <span class="sug">建议：{{ suggestOf(o) }}</span>
                <b class="ev" :class="{neg:(o.expected_net_return||0)<0}">{{ evText(o) }}</b>
              </div>
              <div class="or2">
                <span class="cap">{{ o.capital_reserved ? '建议 '+kU(o.capital_reserved) : '暂不建议' }}</span>
                <span class="rsk" :class="rskClass(o)">{{ rskText(o) }}</span>
                <span class="age">{{ ago }}</span>
                <span class="fill"></span>
                <template v-if="selected===o.symbol">
                  <button class="ob gold" :disabled="!isOperator||!canOpen||o.risk_status?.level!=='NORMAL'"
                          :title="!isOperator?'只读账号:需操作员权限':''"
                          @click.stop="oppAct(o,'opportunity_to_workbench')">送入工作台</button>
                  <button class="ob" :disabled="!isOperator" :title="!isOperator?'只读账号:需操作员权限':''" @click.stop="oppAct(o,'opportunity_watch')">加入观察</button>
                  <button class="ob" :disabled="!isOperator" :title="!isOperator?'只读账号:需操作员权限':''" @click.stop="oppAct(o,'opportunity_ignore')">忽略</button>
                  <button class="ob" @click.stop="basis=o">查看依据</button>
                </template>
                <span v-else class="next">送入工作台 →</span>
              </div>
            </div>
            <div v-if="!oppsFiltered.length" class="empty">暂无{{ oppFilt }}候选（LAB 与顾问持续扫描中）</div>
          </div>
          <div class="wft">AiCoin / K线 / 资金费分布 / 成本拆解 → 「查看依据」内展开，不进主表</div>
        </div>
        <!-- 屏2·持仓墙 fill -->
        <div class="wall w2" v-show="!focus || focus==='屏2·持仓墙'">
          <div class="whd"><b>持仓墙 · 一行=一个经济组合</b>
            <span class="views">
              <span v-for="v in POS_VIEWS" :key="v.k" class="fc" :class="{on:posView===v.k}" @click="posView=v.k">
                {{ v.k }}<b v-if="v.n(counts)!=null" :class="{redn:v.k==='需要处理'&&v.n(counts)>0}">{{ v.n(counts) }}</b>
              </span>
            </span>
          </div>
          <div class="ptable">
            <div class="phead">
              <span style="width:84px">币种</span><span style="width:56px">策略</span>
              <span style="width:50px">自/人</span><span style="width:92px">当前阶段</span>
              <span style="width:72px">投入</span><span style="width:84px">已确认收益</span>
              <span style="width:106px">下一关键时间</span><span style="width:96px">风险</span>
              <span class="fill">下一步（唯一主动作）</span>
            </div>
            <div v-for="p in posFiltered" :key="p.work_item_id" class="prow"
                 :class="{sel:selected===p.symbol}" @click="selected=p.symbol">
              <span style="width:84px;color:var(--mix-gold,#F0B90B);font-weight:800" class="t1b">{{ p.symbol }} ▸</span>
              <span style="width:56px" class="t2b">{{ p.strategy_code }}</span>
              <span style="width:50px" :class="autoClass(p)">{{ autoCn(p.automation_mode) }}</span>
              <span style="width:92px" :class="stageClass(p)">{{ p.stage_detail || p.workflow_stage }}</span>
              <span style="width:72px" class="t2">{{ kU(p.capital_reserved) }}</span>
              <span style="width:84px" class="pnl" :class="pnlClass(p.confirmed_pnl)">{{ pnlText(p.confirmed_pnl) }}</span>
              <span style="width:106px" class="t2">{{ p.next_deadline || 'N/A' }}</span>
              <span style="width:96px" :class="rskClass(p)">{{ rskShort(p) }}</span>
              <span class="fill"><button class="ob" :class="{red:isUrgent(p)}" @click.stop="mainAction(p)">{{ mainActionLabel(p) }}</button></span>
            </div>
            <div v-if="!posFiltered.length" class="empty">当前视图无组合</div>
          </div>
          <div class="wft">▸ 行展开=双腿/借币/订单/Saga ｜ 主动作只显示当前允许的一项（撤单/补对冲/减仓/平仓/买回/还币/修复）</div>
        </div>
        <!-- 屏3·风控墙 420 -->
        <div class="wall w3" v-show="!focus || focus==='屏3·风控墙'">
          <div class="whd"><b>风控墙</b><i>必须处理优先</i></div>
          <div class="rbody">
            <div v-if="p0" class="must">
              <b class="mtitle">必须处理 · {{ p0.severity==='fatal'?'P0':'P1' }} <i :class="'vx-'+p0.venue" style="font-style:normal">{{ p0.venue }}</i> {{ p0.rule }}</b>
              <div class="qa"><i>发生了什么</i><span>{{ p0.title || p0.detail || 'N/A' }}</span></div>
              <div class="qa"><i>影响多少</i><span>{{ p0.detail || 'N/A' }}</span></div>
              <div class="qa"><i>系统已做</i><span>风险权威已按能力位限制该范围新增（{{ p0.state }}）</span></div>
              <div class="qa"><i>建议下一步</i><span>进风险中心处置；命中 {{ p0.hit_count }} 次 · {{ ageCn(p0.age_sec) }}</span></div>
            </div>
            <div v-else class="riskrow okrow"><FIcon name="check" :size="12"/> 当前无必须处理事件</div>
            <div class="riskrow" :class="{warnrow:restrictedN>0}">
              <span class="ri"><FIcon name="warn" :size="14"/></span>
              <div class="rt"><b>平台/账户限制 · {{ restrictedN }}</b>
                <span>{{ restrictedText }}</span></div>
            </div>
            <div class="riskrow">
              <span class="ri"><FIcon name="tool" :size="14"/></span>
              <div class="rt"><b>维护排空 · {{ maintText }}</b>
                <span>{{ snap?.site_maintenance_note || '无进行中维护' }}</span></div>
            </div>
            <div class="riskrow" :class="{warnrow:reconN>0}">
              <span class="ri"><FIcon name="shield" :size="14"/></span>
              <div class="rt"><b>账目核对 · {{ reconN }} 项待清</b>
                <span>{{ reconText }}</span></div>
            </div>
            <div class="riskrow" :class="{warnrow:sysAbn>0}">
              <span class="ri"><FIcon name="alert" :size="14"/></span>
              <div class="rt"><b>系统异常 · {{ sysAbn }}</b>
                <span>{{ sysAbnText }}</span></div>
            </div>
            <div class="fillv"></div>
            <div class="health">
              <i>业务健康（CPU/Redis/心跳 → 系统状态·专家详情）</i>
              <div class="hrow">
                <span v-for="h in health" :key="h.k" class="hcell" :class="h.cls">
                  <b class="dot"></b>{{ h.k }} {{ h.v }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- 查看依据抽屉(不进主表) -->
    <el-drawer v-model="basisOpen" :title="'依据 · '+(basis?.symbol||'')" size="420px">
      <div v-if="basis" class="basis">
        <p>产品：{{ basis.strategy_code }} ｜ 路线：{{ basis.route || 'N/A' }}</p>
        <p>风调后期望：{{ evText(basis) }} ｜ 建议规模：{{ kU(basis.capital_reserved) }}</p>
        <p>风险状态：{{ basis.risk_status?.level }} {{ basis.risk_status?.reason }}</p>
        <p>阶段：{{ basis.workflow_stage }}（{{ basis.stage_detail }}）｜ automation：{{ basis.automation_mode }}</p>
        <p class="t3">AiCoin 研判/K 线 → 机会与研判页；本抽屉只读,不提供开仓入口。</p>
      </div>
    </el-drawer>
  </div>
</template>
<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { mixApi } from '../../api/mix'
import { useV6Snapshot } from '../../composables/useV6'
import V6StatusBar from '../../components/V6StatusBar.vue'

const router = useRouter()
const { snap, stale, canOpen, isOperator, ago } = useV6Snapshot()
const opName = ref(localStorage.getItem('mix_op_name') || 'operator')
const focus = ref('')
const selected = ref('')
const oppFilt = ref('待处理')
const posView = ref('需要处理')
const pausing = ref(false)
const basis = ref(null)
const basisOpen = computed({ get: () => !!basis.value, set: v => { if (!v) basis.value = null } })
const labNote = ref('')

const OPP_FILTS = ['待处理', '可执行', '继续观察', '已暂停']
const POS_VIEWS = [
  { k: '需要处理', n: c => c?.abnormal ?? null },
  { k: '进行中', n: c => (c ? (c.executing + c.holding) : null) },
  { k: '退出中', n: c => c?.exiting ?? null },
  { k: '已完成', n: () => null },
]

const counts = computed(() => snap.value?.counts)
const opps = computed(() => snap.value?.opportunities || [])
const oppTotal = computed(() => snap.value?.counts?.candidates_raw ?? opps.value.length)
const positions = computed(() => snap.value?.positions || [])
const incidents = computed(() => snap.value?.incidents || [])
const p0 = computed(() => incidents.value[0] || null)

const oppsFiltered = computed(() => {
  const list = opps.value
  if (oppFilt.value === '可执行') return list.filter(o => o.risk_status?.level === 'NORMAL' && canOpen.value)
  if (oppFilt.value === '继续观察') return list.filter(o => !o.capital_reserved)
  if (oppFilt.value === '已暂停') return list.filter(o => o.risk_status?.level !== 'NORMAL')
  return list
})
const posFiltered = computed(() => {
  const list = positions.value
  if (posView.value === '需要处理') {
    const bad = list.filter(p => p.workflow_stage === 'RECONCILING' || isUrgent(p))
    return bad.length ? bad : list
  }
  if (posView.value === '进行中') return list.filter(p => ['RESERVED', 'EXECUTING', 'HOLDING'].includes(p.workflow_stage))
  if (posView.value === '退出中') return list.filter(p => p.workflow_stage === 'EXITING')
  if (posView.value === '已完成') return []
  return list
})
const restrictedN = computed(() => {
  const vs = snap.value?.policy?.nav ? snap.value.policy : null
  return incidents.value.filter(i => i.state !== 'CLOSED' && i.severity !== 'info').length ? undefined : undefined
})
// 平台限制行:直接数 policy 受限 venue(经 snapshot.policy 无 venues,退而用 incidents venue 数)
const restrictedVenues = computed(() => [...new Set(incidents.value.filter(i => i.venue && i.severity === 'fatal').map(i => i.venue))])
const restrictedText = computed(() => restrictedVenues.value.length
  ? `${restrictedVenues.value.join('/')} 受限 · 已停新增` : '全部平台正常')
const maintText = computed(() => {
  const s = snap.value?.site_maintenance_state
  return (!s || s === 'NORMAL' || s === 'CLOSED') ? '无进行中' : s
})
const reconItems = computed(() => positions.value.filter(p => p.workflow_stage === 'RECONCILING'))
const reconN = computed(() => reconItems.value.length)
const reconText = computed(() => reconN.value
  ? reconItems.value.map(p => `${p.symbol}(${p.stage_detail})`).join(' · ') : '账本投影无待清差异')
const sysAbnItems = computed(() => incidents.value.filter(i => i.severity !== 'fatal'))
const sysAbn = computed(() => sysAbnItems.value.length)
const sysAbnText = computed(() => sysAbn.value
  ? sysAbnItems.value.slice(0, 2).map(i => `${i.venue||''} ${i.title||i.rule}`).join(' · ') : '无')
const health = computed(() => {
  const lh = snap.value?.ledger_health || {}
  const pol = snap.value?.policy || {}
  return [
    { k: '行情', v: pol.stale ? '过期' : '正常', cls: pol.stale ? 'hy' : 'hg' },
    { k: '执行', v: (counts.value?.abnormal || 0) > 0 ? '有异常' : '正常', cls: (counts.value?.abnormal || 0) > 0 ? 'hy' : 'hg' },
    { k: '账本', v: lh.status || 'N/A', cls: lh.status === '正常' ? 'hg' : 'hy' },
    { k: '通知', v: '正常', cls: 'hg' },
  ]
})

function suggestOf(o) {
  if (o.risk_status?.level !== 'NORMAL') return '继续观察'
  return (o.expected_net_return || 0) >= 15 ? '辅助执行' : (o.capital_reserved ? '自动执行' : '继续观察')
}
function evText(o) {
  const v = o.expected_net_return
  return v == null ? 'N/A' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)} bps/日`
}
function kU(v) { if (v == null) return 'N/A'; const n = Number(v); return n >= 1000 ? (n / 1000).toFixed(1) + 'K U' : n.toFixed(0) + ' U' }
function rskClass(o) { const l = o.risk_status?.level; return l === 'NORMAL' ? 't3' : (['WATCH','RECOVERY_WATCH'].includes(l) ? 'amber' : 'orange') }
function rskText(o) { const r = o.risk_status; if (!r) return '风险：N/A'; return r.level === 'NORMAL' ? '风险：低 · 全所正常' : `主要风险：${r.reason || r.level}` }
function rskShort(p) { const r = p.risk_status; if (!r) return 'N/A'; if (p.workflow_stage === 'RECONCILING') return `P0 · ${p.stage_detail}`; return r.level === 'NORMAL' ? '低' : `${r.reason || r.level}` }
function autoCn(m) { return { AUTO: '自动', ASSISTED: '辅助', MANUAL: '人工' }[m] || 'N/A' }
function autoClass(p) { return p.automation_mode === 'AUTO' ? 'green' : 'amber' }
function stageClass(p) {
  if (p.workflow_stage === 'RECONCILING') return 'redtxt'
  if (p.workflow_stage === 'EXITING') return 'amber'
  if (p.workflow_stage === 'HOLDING' && (p.next_deadline || '').includes(':')) return 'green'
  return 'green'
}
function pnlClass(v) { return v == null ? 't3' : (v >= 0 ? 'green' : 'redtxt') }
function pnlText(v) { return v == null ? 'N/A' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)} U` }
function isUrgent(p) { return p.workflow_stage === 'RECONCILING' || (p.risk_status && !['NORMAL','WATCH'].includes(p.risk_status.level)) }
function ageCn(s) { if (s == null) return ''; return s < 3600 ? `${Math.floor(s/60)}m` : `${Math.floor(s/3600)}h` }
function mainActionLabel(p) {
  if (p.workflow_stage === 'RECONCILING') return '修复'
  if (p.workflow_stage === 'EXITING') return p.strategy_code === 'C3.S' ? '还币' : '撤单'
  if (isUrgent(p)) return '减仓'
  return '查看'
}
function mainAction(p) {
  selected.value = p.symbol
  if (p.strategy_code === 'C3.S') { router.push('/mix/slots'); return }
  if (p.workflow_stage === 'RECONCILING' || isUrgent(p)) { router.push('/mix/venuerisk'); return }
  router.push('/mix/workbench')
}
async function oppAct(o, ctype) {
  try {
    const r = await mixApi.v6Command({
      command_type: ctype, params: { symbol: o.symbol, strategy_code: o.strategy_code },
      idempotency_key: `${ctype}:${o.symbol}:${Date.now() >> 13}`,
    })
    ElMessage.success(r?.result?.note || '已登记')
    if (ctype === 'opportunity_to_workbench') router.push('/mix/workbench')
  } catch (e) { ElMessage.error(e?.detail || e?.error || '命令被拒绝') }
}
async function pauseNewRisk() {
  try {
    await ElMessageBox.confirm('全局追加 NO_NEW_RISK（经风险权威通道,venue 级限制不受影响;减险/平仓不受限）。确认？', '暂停新增风险', { type: 'warning' })
  } catch { return }
  pausing.value = true
  try {
    await mixApi.v6Command({ command_type: 'pause_new_risk', params: { reason: 'V6中控台:操作员暂停新增' } })
    ElMessage.success('已提交:全局 NO_NEW_RISK(risk-ledger ≤30s 合并)')
  } catch (e) { ElMessage.error(e?.detail || '失败') } finally { pausing.value = false }
}
function openTopRisk() { router.push(p0.value ? `/mix/venue/${p0.value.venue}` : '/mix/venuerisk') }

mixApi.uxPageview('console')   // M5 收敛门槛数据:中控台使用量(退役观察)
const labLatestId = ref(0)
watch(snap, async (s) => {
  if (s && !labNote.value) {
    try {
      const ob = await mixApi.v6LabOutbox()
      const rows = ob?.data || []
      if (rows.length) {
        labLatestId.value = rows[0].id
        // 已读机制:按最新摘要 id 记忆;有更新的摘要会再次提醒
        if (Number(localStorage.getItem('mix_lab_read_id') || 0) < rows[0].id)
          labNote.value = `LAB 有新结果（${rows[0].project_id} · ${rows[0].title}）`
      }
    } catch { /* LAB 不可达不影响生产 */ }
  }
}, { once: true })
function dismissLab() {
  localStorage.setItem('mix_lab_read_id', String(labLatestId.value || 0))
  labNote.value = ''
}
</script>
<style scoped>
.v6con{height:100%;display:flex;flex-direction:column;background:var(--mix-bg);min-height:0}
.body{flex:1;display:flex;flex-direction:column;gap:8px;padding:8px 12px;min-height:0}
.toprow{display:flex;align-items:center;justify-content:space-between;gap:10px;flex:none}
.focus{display:flex;gap:2px;background:var(--mix-panel);border-radius:6px;padding:2px}
.fitem{font-size:11px;color:var(--mix-t2);padding:4px 12px;border-radius:5px;cursor:pointer}
.fitem.on{background:var(--mix-card2);color:var(--mix-t1);font-weight:700}
.linknote{font-size:10.5px;color:var(--mix-blue)}
.quick{display:flex;gap:8px}
.qb{height:32px;padding:0 12px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;border:1px solid var(--mix-border);background:var(--mix-card2);color:var(--mix-t1)}
.qb.red{background:#F6465D14;border-color:#F6465D66;color:var(--mix-red)}
.qb.gold{background:#F0B90B1F;border-color:#F0B90B4D;color:var(--mix-accent)}
.qb:disabled{opacity:.5;cursor:not-allowed}
.walls{flex:1;display:flex;gap:8px;min-height:0}
.wall{background:var(--mix-card);border:1px solid var(--mix-border);border-radius:8px;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.w1{width:462px;flex:none}.w2{flex:1;min-width:0}.w3{width:420px;flex:none}
.whd{display:flex;align-items:center;justify-content:space-between;padding:8px 12px 6px}
.whd b{font-size:12.5px;color:var(--mix-t1)}
.whd i{font-size:9.5px;color:var(--mix-t3);font-style:normal}
.filts{display:flex;gap:4px;padding:0 10px 6px}
.fc{font-size:10px;color:var(--mix-t2);padding:2px 9px;border:1px solid var(--mix-border);border-radius:5px;background:var(--mix-panel);cursor:pointer;display:inline-flex;gap:4px;align-items:center}
.fc.on{color:var(--mix-accent);font-weight:700;background:var(--mix-card2);border-color:#F0B90B4D}
.fc b{font-size:9.5px;color:var(--mix-t1)}
.fc b.redn{color:var(--mix-red)}
.labbar{font-size:10px;color:var(--mix-blue);background:#4A9CFF14;padding:5px 12px;border-top:1px solid var(--mix-border);border-bottom:1px solid var(--mix-border)}
.labbar a{color:var(--mix-blue);cursor:pointer;text-decoration:underline}
.labdismiss{float:right;cursor:pointer;color:var(--mix-t3);padding:0 4px}
.labdismiss:hover{color:var(--mix-t1)}
.olist{flex:1;overflow:auto;min-height:0}
.orow{padding:6px 12px;border-bottom:1px solid var(--mix-border);cursor:pointer;display:flex;flex-direction:column;gap:3px}
.orow.sel{background:var(--mix-card2);border-left:2px solid var(--mix-blue)}
.or1{display:flex;align-items:center;gap:6px}
.sym{font-size:11.5px;font-weight:700;color:var(--mix-t1)}
.sug{font-size:10px;color:var(--mix-t2)}
.ev{margin-left:auto;font-size:11.5px;color:var(--mix-green)}
.ev.neg{color:var(--mix-red)}
.or2{display:flex;align-items:center;gap:8px;font-size:9.5px}
.cap{color:var(--mix-t3)}.age{color:var(--mix-t3);font-size:9px}
.rsk.orange,.orange{color:#FF8A3D}.rsk.amber,.amber{color:var(--mix-accent)}
.t3{color:var(--mix-t3)}.t2{color:var(--mix-t2)}.t1b{color:var(--mix-t1);font-weight:700}.t2b{color:var(--mix-t2);font-weight:700}
.green{color:var(--mix-green)}.redtxt{color:var(--mix-red)}
.fill{flex:1;min-width:0}.fillv{flex:1}
.next{color:var(--mix-t3);font-size:9.5px}
.ob{font-size:9px;font-weight:700;padding:2px 7px;border-radius:4px;border:1px solid var(--mix-border);background:var(--mix-card2);color:var(--mix-t1);cursor:pointer}
.ob.gold{background:#F0B90B1F;border-color:#F0B90B4D;color:var(--mix-accent)}
.ob.red{background:#F6465D14;border-color:#F6465D66;color:var(--mix-red)}
.ob:disabled{opacity:.45;cursor:not-allowed}
.wft{font-size:8.5px;color:var(--mix-t3);padding:5px 12px;border-top:1px solid var(--mix-border)}
.views{display:flex;gap:4px}
.ptable{flex:1;overflow:auto;min-height:0;display:flex;flex-direction:column}
/* 小屏兜底:行保底宽→容器横向滚动,绝不压缩裁切列(VPT挤成竖条课) */
.phead,.prow{min-width:790px}
.phead span,.prow span{flex-shrink:0}
.phead .fill,.prow .fill{flex-shrink:1}
.phead{display:flex;align-items:center;background:var(--mix-panel);border-top:1px solid var(--mix-border);border-bottom:1px solid var(--mix-border);height:22px;flex:none;position:sticky;top:0;z-index:1}
.phead span{font-size:8.5px;font-weight:700;color:var(--mix-t3);padding:0 7px;white-space:nowrap;overflow:hidden}
.prow{display:flex;align-items:center;height:30px;border-bottom:1px solid var(--mix-border);cursor:pointer;flex:none}
.prow span{font-size:9.5px;padding:0 7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prow.sel{background:var(--mix-card2);border-left:2px solid var(--mix-blue)}
.pnl{font-weight:700}
.empty{padding:24px;text-align:center;color:var(--mix-t3);font-size:11px}
.rbody{flex:1;display:flex;flex-direction:column;gap:6px;padding:2px 10px 8px;overflow:auto;min-height:0}
.must{background:#F6465D0D;border:1px solid #F6465D66;border-radius:6px;padding:8px 10px;display:flex;flex-direction:column;gap:3px}
.mtitle{font-size:11.5px;color:var(--mix-red)}
.qa{display:flex;gap:6px;font-size:9.5px}
.qa i{color:var(--mix-t3);font-style:normal;flex:none;width:56px;font-size:9px}
.qa span{color:var(--mix-t2);line-height:1.35}
.riskrow{display:flex;gap:7px;align-items:center;background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:6px 10px}
.riskrow.okrow{color:var(--mix-green);font-size:10.5px;font-weight:700}
.riskrow.warnrow .rt b{color:#FF8A3D}
.ri{font-size:13px;flex:none}
.rt{display:flex;flex-direction:column;gap:1px;min-width:0}
.rt b{font-size:10.5px;color:var(--mix-t2)}
.rt span{font-size:9px;color:var(--mix-t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.health{background:var(--mix-panel);border:1px solid var(--mix-border);border-radius:6px;padding:7px 10px;display:flex;flex-direction:column;gap:4px}
.health i{font-size:8.5px;color:var(--mix-t3);font-style:normal}
.hrow{display:flex;gap:6px}
.hcell{flex:1;height:26px;display:flex;align-items:center;justify-content:center;gap:4px;border-radius:5px;font-size:9.5px;font-weight:700}
.hcell .dot{width:7px;height:7px;border-radius:50%}
.hcell.hg{background:#0ECB810F;color:var(--mix-green)}.hcell.hg .dot{background:var(--mix-green)}
.hcell.hy{background:#F0B90B14;color:var(--mix-accent)}.hcell.hy .dot{background:var(--mix-accent)}
.basis p{font-size:12px;color:var(--mix-t1);margin:6px 0}
.basis .t3{color:var(--mix-t3);font-size:11px}
.whd{flex-wrap:wrap;gap:4px}
@media (max-width:1680px){ .w1{width:400px}.w3{width:380px} }
@media (max-width:1500px){ .w1{width:360px}.w3{width:340px} }
@media (max-width:1360px){ .walls{flex-wrap:wrap;overflow:auto}.w1,.w3{width:calc(50% - 4px);min-height:300px}.w2{width:100%;flex:none;order:-1;min-height:320px} }
@media (max-width:760px){ .w1,.w2,.w3{width:100%} .toprow{flex-wrap:wrap} }
</style>
