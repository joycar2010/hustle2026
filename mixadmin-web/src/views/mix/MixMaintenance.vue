<template>
  <div class="maint">
    <RiskStatusBar />
    <!-- 无活跃维护:启动确认页(影响预览) -->
    <div v-if="!active" class="card">
      <div class="chd2"><b>网站维护与交易排空</b><span class="dimtxt">V2 §7:两层状态,单一风险权威——映射既有 policy override,不建平行 kill switch</span></div>
      <div class="ptypes">
        <label class="pt" :class="{on: form.mtype==='SITE_AND_DRAIN'}"><input type="radio" value="SITE_AND_DRAIN" v-model="form.mtype" />
          <b>网站维护 + 交易排空</b><span class="dimtxt">立即停止新增人工/策略风险,逐步退出生产仓位(例行默认)</span></label>
        <label class="pt" :class="{on: form.mtype==='SITE_ONLY'}"><input type="radio" value="SITE_ONLY" v-model="form.mtype" />
          <b>仅网站维护</b><span class="dimtxt">只显示公告,不改变交易权限</span></label>
      </div>
      <div class="chd2"><b>影响预览</b><el-button size="small" @click="loadPreview" :loading="pvBusy">刷新</el-button></div>
      <div class="preview">
        <div class="pv"><span>在管组合</span><b :class="{bad:(pv.live_combos||[]).length}">{{ (pv.live_combos||[]).length }}</b></div>
        <div class="pv"><span>单腿残腿</span><b :class="{bad:(pv.single_legs||[]).length}">{{ (pv.single_legs||[]).length }}</b></div>
        <div class="pv"><span>C3 非终态坑位</span><b :class="{bad:(pv.c3_open_pits||[]).length}">{{ (pv.c3_open_pits||[]).length }}</b></div>
        <div class="pv"><span>未决开仓提案</span><b :class="{bad:pv.pending_proposals}">{{ pv.pending_proposals ?? 'N/A' }}</b></div>
        <div class="pv"><span>修复意图在途</span><b>{{ pv.repair_intents ?? 0 }}</b></div>
        <div class="pv"><span>预计可否直接排空清</span><b :class="pv.clear?'ok':'bad'">{{ pv.clear ? '可清' : '有残留(将进 DRAIN_BLOCKED)' }}</b></div>
      </div>
      <div class="disallow">启动后将禁止:开仓/加仓/增债/新推送/新借币/新增 maker 阶梯 ｜ 仍允许:撤单/减仓/买回/还币/补对冲/风险修复</div>
      <el-form label-width="90px" size="small" class="sf">
        <el-form-item label="原因"><el-input v-model="form.reason" placeholder="维护原因" /></el-form-item>
        <el-form-item label="维护说明"><el-input v-model="form.note" type="textarea" :rows="2" placeholder="将展示给客户前台" /></el-form-item>
        <el-form-item label="截止(分)"><el-input v-model="form.deadline_min" style="width:120px" /></el-form-item>
        <el-form-item label="确认短语"><el-input v-model="form.confirm_phrase" placeholder="须输入:开始维护并排空" /></el-form-item>
        <el-form-item label="TOTP" v-if="true"><el-input v-model="form.totp_code" placeholder="已绑定二次认证则必填" maxlength="6" style="width:160px" /></el-form-item>
      </el-form>
      <el-button type="danger" :loading="busy" @click="start">开始维护并排空</el-button>
      <div class="fnote">生成审计编号;当前一人操作不强制双人审批,但须确认短语+重新认证。</div>
    </div>

    <!-- 有活跃维护:进度页 -->
    <div v-else class="card">
      <div class="chd2"><b>维护 #{{ prog.request.id }}</b>
        <span class="mch" :class="stCls(prog.request.state)">{{ stLabel(prog.request.state) }}</span>
        <span class="dimtxt">{{ prog.request.mtype }} · 由 {{ prog.request.created_by }} · 截止 {{ (prog.request.deadline_at||'').slice(0,16) }}</span>
        <span class="grow" /><el-button size="small" @click="loadProgress" :loading="pgBusy">刷新</el-button></div>
      <!-- 阶段条 -->
      <div class="stages">
        <span v-for="(s,i) in STAGES" :key="s.k" class="stage" :class="stageState(s.k)">
          <i>{{ i+1 }}</i>{{ s.t }}</span>
      </div>
      <!-- 排空清单 -->
      <div class="chd2" style="margin-top:10px"><b>排空清单(实时)</b>
        <span class="dimtxt" v-if="!prog.checklist.clear">有残留——DRAIN_BLOCKED 时须 DrainPlan,绝不自动砍仓</span></div>
      <div class="preview">
        <div class="pv"><span>在管组合</span><b :class="{bad:(prog.checklist.live_combos||[]).length}">{{ (prog.checklist.live_combos||[]).map(c=>c.symbol).join(',') || '无' }}</b></div>
        <div class="pv"><span>单腿</span><b :class="{bad:(prog.checklist.single_legs||[]).length}">{{ (prog.checklist.single_legs||[]).join(',') || '无' }}</b></div>
        <div class="pv"><span>C3 坑位</span><b :class="{bad:(prog.checklist.c3_open_pits||[]).length}">{{ (prog.checklist.c3_open_pits||[]).length }}</b></div>
        <div class="pv"><span>未决提案</span><b :class="{bad:prog.checklist.pending_proposals}">{{ prog.checklist.pending_proposals ?? 'N/A' }}</b></div>
      </div>
      <!-- 动作 -->
      <div class="acts">
        <el-button v-if="['ANNOUNCED','DRAINING','DRAIN_BLOCKED'].includes(prog.request.state) && prog.request.mtype!=='SITE_ONLY'"
          type="warning" :loading="busy" @click="advance">推进阶段 →</el-button>
        <template v-if="prog.request.state==='DRAIN_BLOCKED'">
          <el-button size="small" @click="drainPlan('EXTEND')">延长排空 +60min</el-button>
          <el-button size="small" type="danger" plain @click="drainPlan('FORCE_EXIT_PROPOSAL')">强制退出提案(仅登记)</el-button>
        </template>
        <el-input v-model="recCode" placeholder="TOTP" maxlength="6" size="small" style="width:120px" />
        <el-button type="success" plain :loading="busy" @click="recover">恢复(健康检查)</el-button>
      </div>
      <div v-if="prog.request.state==='DRAIN_BLOCKED'" class="blocked"><FIcon name="warn" :size="12"/> 排空受阻:有残留仓位/坑位/提案。EXIT_ONLY 是能力集合不是自动平仓;须人工减仓还币或提交 DrainPlan,不会因截止砍仓,有仓不显示"完成"。</div>
      <div v-if="recFail" class="blocked">恢复未过:{{ recFail }}</div>
      <!-- DrainPlan 历史 -->
      <div v-if="(prog.drain_plans||[]).length" class="chd2" style="margin-top:8px"><b>DrainPlan 决策</b></div>
      <div v-for="(dp,i) in prog.drain_plans||[]" :key="i" class="logline"><b>{{ dp.decision }}</b> {{ dp.note }} <span class="dimtxt">{{ dp.created_by }} · {{ (dp.created_at||'').slice(0,16) }}</span></div>
      <!-- 进度日志 -->
      <div class="chd2" style="margin-top:8px"><b>阶段日志</b></div>
      <div v-for="(l,i) in prog.logs||[]" :key="i" class="logline"><span class="lst">{{ l.stage }}</span><span class="dimtxt">{{ (l.recorded_at||'').slice(5,16) }} · {{ l.actor }}</span></div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const STAGES = [{ k: 'ANNOUNCED', t: '已公告' }, { k: 'DRAINING', t: '禁止新增' }, { k: 'DRAIN2', t: '撤单/对冲' },
  { k: 'DRAIN3', t: '减仓还币' }, { k: 'MAINTENANCE', t: 'RECON/维护' }, { k: 'CLOSED', t: '恢复' }]
const active = ref(false)
const form = ref({ mtype: 'SITE_AND_DRAIN', reason: '', note: '', deadline_min: 120, confirm_phrase: '', totp_code: '' })
const pv = ref({}); const prog = ref({ request: {}, checklist: {}, logs: [], drain_plans: [] })
const busy = ref(false); const pvBusy = ref(false); const pgBusy = ref(false)
const recCode = ref(''); const recFail = ref('')
let t1 = null; let curId = null
const stLabel = s => ({ ANNOUNCED: '已公告', DRAINING: '排空中', DRAIN_BLOCKED: '排空受阻', MAINTENANCE: '维护中', RECOVERY_CHECK: '恢复检查', CLOSED: '已关闭' }[s] || s)
const stCls = s => ({ ANNOUNCED: 'watch', DRAINING: 'nonew', DRAIN_BLOCKED: 'red', MAINTENANCE: 'red', RECOVERY_CHECK: 'recov', CLOSED: 'ok' }[s] || 'ok')
const ORDER = ['ANNOUNCED', 'DRAINING', 'DRAIN_BLOCKED', 'MAINTENANCE', 'CLOSED']
function stageState(k) {
  const cur = prog.value.request.state
  const ci = ORDER.indexOf(cur === 'DRAIN_BLOCKED' ? 'DRAINING' : cur)
  const map = { ANNOUNCED: 0, DRAINING: 1, DRAIN2: 1, DRAIN3: 1, MAINTENANCE: 3, CLOSED: 4 }
  const si = map[k]
  if (cur === 'DRAIN_BLOCKED' && (k === 'DRAIN2' || k === 'DRAIN3')) return 'blocked'
  return si < ci ? 'done' : si === ci || (si <= 3 && cur === 'MAINTENANCE') ? 'cur' : ''
}
async function loadStatus() {
  try {
    const st = await mixApi.maintStatus()
    if (st.state && st.state !== 'NORMAL') {
      active.value = true
      const p = await mixApi.maintProgress(st.id || curId || (prog.value.request.id))
      if (p) { prog.value = p; curId = p.request.id }
    } else { active.value = false; loadPreview() }
  } catch (e) { /* */ }
}
async function loadPreview() {
  pvBusy.value = true
  try { pv.value = await mixApi.maintPreview() } catch (e) { /* */ } finally { pvBusy.value = false }
}
async function loadProgress() {
  if (!curId) return
  pgBusy.value = true
  try { prog.value = await mixApi.maintProgress(curId) } catch (e) { /* */ } finally { pgBusy.value = false }
}
async function start() {
  busy.value = true
  try {
    const r = await mixApi.maintStart(form.value)
    ElMessage.success(`维护 #${r.id} 已启动(${r.state})`); curId = r.id; loadStatus()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '启动失败') } finally { busy.value = false }
}
async function advance() {
  busy.value = true
  try {
    const r = await mixApi.maintAdvance(curId)
    ElMessage[r.ok === false ? 'warning' : 'success'](`→ ${stLabel(r.state)}${r.state === 'DRAIN_BLOCKED' ? '(有残留,须 DrainPlan)' : ''}`)
    loadProgress()
  } catch (e) { ElMessage.error(e?.detail || '失败') } finally { busy.value = false }
}
async function drainPlan(decision) {
  try {
    await mixApi.maintDrainPlan(curId, { decision, extend_min: 60, note: decision === 'EXTEND' ? '延长排空' : '强制退出提案(人工执行)' })
    ElMessage.success(decision === 'EXTEND' ? '已延长排空' : '强制退出提案已登记'); loadProgress()
  } catch (e) { ElMessage.error(e?.detail || '失败') }
}
async function recover() {
  busy.value = true; recFail.value = ''
  try {
    const r = await mixApi.maintRecover(curId, recCode.value)
    if (r.ok) { ElMessage.success('已恢复(GLOBAL NORMAL,venue 级 RECOVERY_WATCH 阶梯生效)'); loadStatus() }
    else { recFail.value = JSON.stringify(r.checks || {}); ElMessage.warning('健康检查未过') }
  } catch (e) { ElMessage.error(e?.detail || '失败') } finally { busy.value = false }
}
onMounted(() => { loadStatus(); t1 = setInterval(() => active.value ? loadProgress() : loadStatus(), 8000) })
onUnmounted(() => t1 && clearInterval(t1))
</script>

<style scoped lang="scss">
.maint { display: flex; flex-direction: column; gap: 10px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; padding: 12px 14px; }
.chd2 { font-size: 13px; font-weight: 700; color: var(--mix-t1, #EAECEF); margin: 8px 0 6px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.bad { color: #F6465D !important; } .ok { color: #0ECB81 !important; }
.ptypes { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.pt { flex: 1; min-width: 260px; border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 12px; cursor: pointer;
  display: flex; flex-direction: column; gap: 3px;
  b { color: var(--mix-t1, #EAECEF); } input { margin-right: 6px; }
  &.on { border-color: #F0B90B; background: rgba(240,185,11,.06); } }
.preview { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin: 4px 0 8px; }
.pv { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 6px; padding: 8px 11px;
  display: flex; flex-direction: column; gap: 2px;
  span { font-size: 10px; color: var(--mix-t3, #5E6673); }
  b { font-size: 14px; color: var(--mix-t1, #EAECEF); } }
.disallow { font-size: 10.5px; color: #F0B90B; background: rgba(240,185,11,.06); border-radius: 6px; padding: 7px 10px; margin-bottom: 8px; }
.sf { max-width: 560px; }
.fnote { font-size: 10px; color: var(--mix-t3, #5E6673); margin-top: 6px; }
.mch { font-weight: 800; font-size: 11px; padding: 2px 9px; border-radius: 5px;
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.watch { background: rgba(240,185,11,.14); color: #F0B90B; }
  &.nonew { background: rgba(255,138,61,.16); color: #FF8A3D; }
  &.red { background: rgba(246,70,93,.16); color: #F6465D; }
  &.recov { background: rgba(140,163,199,.16); color: #8CA3C7; } }
.stages { display: flex; gap: 4px; flex-wrap: wrap; }
.stage { flex: 1; min-width: 96px; text-align: center; font-size: 10.5px; padding: 8px 4px; border-radius: 6px;
  background: var(--mix-panel, #12151A); color: var(--mix-t3, #5E6673); border: 1px solid var(--mix-border, #262B33);
  i { display: block; font-style: normal; font-weight: 800; margin-bottom: 2px; }
  &.done { color: #35b57c; border-color: rgba(14,203,129,.3); }
  &.cur { color: #F0B90B; border-color: #F0B90B; background: rgba(240,185,11,.08); }
  &.blocked { color: #F6465D; border-color: rgba(246,70,93,.4); } }
.acts { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 10px 0; }
.blocked { font-size: 11px; color: #F6465D; background: rgba(246,70,93,.06); border-radius: 6px; padding: 8px 10px; }
.logline { font-size: 11px; color: var(--mix-t2, #848E9C); padding: 3px 0; display: flex; gap: 8px; align-items: center;
  b { color: var(--mix-t1, #EAECEF); } }
.lst { font-weight: 700; color: var(--mix-t1, #EAECEF); min-width: 120px; }
</style>
