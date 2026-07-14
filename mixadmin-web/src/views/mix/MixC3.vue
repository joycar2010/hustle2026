<template>
  <div class="c3">
    <RiskStatusBar />
    <el-tabs v-model="tab">
      <!-- ① 人工推送工作台(qI0s6) -->
      <el-tab-pane label="人工推送" name="push">
        <div class="tri">
          <div class="card">
            <div class="chd2"><b>推送案件(八字段)</b><span class="dimtxt">登记≠下单:不进命令队列、不触发借币</span></div>
            <el-form label-width="86px" size="small" class="pf">
              <el-form-item label="币种"><el-input v-model="form.symbol" placeholder="如 FILUSDT" @change="brief" /></el-form-item>
              <el-form-item label="来源"><el-select v-model="form.source"><el-option v-for="o in ['AiCoin研判','人工盯盘','社群线索','榜单']" :key="o" :value="o" /></el-select></el-form-item>
              <el-form-item label="理由"><el-input v-model="form.reason" type="textarea" :rows="2" /></el-form-item>
              <el-form-item label="预期结构"><el-select v-model="form.structure"><el-option v-for="o in ['放量拉升','横盘吸筹','事件驱动','高费差','不确定']" :key="o" :value="o" /></el-select></el-form-item>
              <el-form-item label="建议金额"><el-input v-model="form.amount" placeholder="USDT,空=按规则 order_amount" /></el-form-item>
              <el-form-item label="失效条件"><el-input v-model="form.invalidation" placeholder="如:点差<0.5% 连2轮" /></el-form-item>
              <el-form-item label="最晚复核"><el-input v-model="form.review_by" placeholder="如:07-15 09:00" /></el-form-item>
              <el-form-item label="尾险预算"><el-input v-model="form.tail_budget" placeholder="如:≤10U" /></el-form-item>
            </el-form>
            <div class="btns">
              <el-button size="small" :loading="busy==='case'" @click="saveCase">登记案件</el-button>
              <el-button size="small" type="warning" :disabled="!gateOk" :loading="busy==='push'"
                :title="gateOk ? '走既有 push_symbol,coin 规则/黑名单/借币闸原样生效' : '风险闸未过,禁止确认'"
                @click="confirmPush">操作员确认推送 →</el-button>
            </div>
          </div>
          <div class="card">
            <div class="chd2"><b>系统补数九宫格</b><span class="dimtxt">{{ form.symbol || '—' }} · 面板60s</span></div>
            <div class="grid9">
              <div class="g"><span>开/平点差</span><b>{{ g.spread ? JSON.stringify(g.spread).slice(0,26) : 'N/A' }}</b></div>
              <div class="g"><span>借币日息%/d</span><b :class="{bad: +g.daily_interest_rate>=1}">{{ g.daily_interest_rate ?? 'N/A' }}</b></div>
              <div class="g"><span>最大可借</span><b>{{ g.max_borrowable ?? 'N/A' }}</b></div>
              <div class="g"><span>借币限额</span><b>{{ g.borrow_limit ?? 'N/A' }}</b></div>
              <div class="g"><span>可借归零(-3045)</span><b :class="{bad: g.no_inventory}">{{ g.no_inventory ? '冷却 '+(g.noinv_remaining_sec??'?')+'s' : '否' }}</b></div>
              <div class="g"><span>还币闸</span><b :class="{bad: g.repayhold}">{{ g.repayhold ? 'repayhold' : '正常' }}</b></div>
              <div class="g"><span>黑名单</span><b :class="{bad: g.blacklist_hit}">{{ g.blacklist_hit ? '命中' : '无' }}</b></div>
              <div class="g"><span>规则金额</span><b>{{ g.order_amount ?? 'N/A' }}</b></div>
              <div class="g"><span>policy(binance)</span><b :class="{bad: !g.policy_can_open}">{{ g.policy_mode ?? 'N/A' }}</b></div>
            </div>
            <div class="chd2" style="padding-top:6px"><b>闸门流水线</b></div>
            <div class="pipe">
              <span v-for="(s,i) in gates" :key="i" class="pstep" :class="s.ok===true?'ok':s.ok===false?'bad2':'na'"
                :title="s.note">{{ i+1 }} {{ s.k }}</span>
            </div>
            <div class="fnote">人工推送→补数→经济闸→风险闸→DRY_RUN→操作员确认→PositionIntent;权威判定在 coin 引擎,此处为预判展示</div>
          </div>
          <div class="card">
            <div class="chd2"><b>案件队列</b><span class="dimtxt">近20,lab_case 只追加</span></div>
            <div v-for="c in cases" :key="c.id" class="lrow">
              <b>{{ c.symbol }}</b><span class="dimtxt">{{ c.stage || c.structure || '' }} · {{ (c.created_at||'').slice(5,16) }}</span>
              <span class="grow" /><span>{{ c.action }}</span>
            </div>
            <div v-if="!cases.length" class="dimtxt pad">无案件</div>
            <div class="chd2" style="padding-top:8px"><b>可借量监控 Top12</b></div>
            <div v-for="b in ov.borrowable_top || []" :key="b.sym" class="lrow">
              <b>{{ b.sym }}</b><span class="grow" />
              <span>可借 {{ b.max_borrowable }}</span><span class="dimtxt">息 {{ b.rate ?? 'N/A' }}%/d</span>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ② 经济组合与生命周期(QuReD) -->
      <el-tab-pane :label="`生命周期 ${ (ov.rows||[]).length }`" name="life">
        <div class="card">
          <div class="chd2"><b>C3 经济组合 · 一行一组合</b>
            <span class="legend"><i v-for="s in STATES" :key="s" class="lg" :class="'st-'+s">{{ s }}</i></span></div>
          <div class="lhead"><span>标的</span><span>子账户</span><span>状态</span><span class="r">借币</span><span class="r">现货卖</span><span class="r">现货买回</span><span class="r">合约多</span><span>发起</span><span>动作</span></div>
          <div v-if="!(ov.rows||[]).length" class="dimtxt pad">无在管 C3 组合</div>
          <template v-for="(r,i) in ov.rows" :key="i">
            <div class="lrow2" :class="{open: exp===i, warn2: STALE_ST.includes(r.status)}" @click="exp = exp===i ? -1 : i">
              <span><b>{{ r.symbol }}</b></span><span>{{ r.sub || '—' }}</span>
              <span><i class="lg" :class="'st-'+r.status">{{ r.status }}</i></span>
              <span class="r">{{ r.borrowed ?? 'N/A' }}</span><span class="r">{{ r.spot_sell ?? 'N/A' }}</span>
              <span class="r">{{ r.spot_buy ?? 'N/A' }}</span><span class="r">{{ r.futures_long ?? 'N/A' }}</span>
              <span>{{ r.opened_at || '—' }}</span>
              <span><el-link @click.stop="$router.push('/mix/slots')">坑位台 →</el-link></span>
            </div>
            <div v-if="exp===i" class="drawer">
              <div class="dcol"><div class="dh">三腿抽屉</div>
                <div class="dline">① 借币腿:{{ r.borrowed ?? 'N/A' }}(杠杆账户)</div>
                <div class="dline">② 现货卖腿:卖 {{ r.spot_sell ?? 'N/A' }} · 买回 {{ r.spot_buy ?? 'N/A' }}</div>
                <div class="dline">③ 对冲腿:合约多 {{ r.futures_long ?? 'N/A' }}(hedge_via_master)</div></div>
              <div class="dcol"><div class="dh">还币预演(只读)</div>
                <div class="dline">应还 = 借币 {{ r.borrowed ?? 'N/A' }} + 利息(面板 interest)</div>
                <div class="dline dimtxt">可买回深度/滑点 N/A(回购深度源待接);还币走坑位台"手动还币/部分还币"(coin 还币闸权威)</div></div>
            </div>
          </template>
          <div class="fnote">九态:PROPOSED→PENDING_BORROW→BORROWED_IDLE→OPENING→OPEN→PENDING_REPAY→REPAYING→CLOSED｜FAILED;非终态滞留超龄由 risk-ledger R3 告警</div>
        </div>
      </el-tab-pane>

      <!-- ③ 风险置顶(ERX5c) -->
      <el-tab-pane label="风险置顶" name="risk">
        <div class="lights">
          <div v-for="l in ov.lights || []" :key="l.k" class="light" :class="l.n===null ? 'na2' : l.n>0 ? 'hot' : 'okl'">
            <div class="lk">{{ l.k }}</div>
            <b class="ln">{{ l.n === null ? 'N/A' : l.n }}</b>
            <div class="ld dimtxt">{{ l.note }}</div>
            <div v-for="(d,j) in l.detail" :key="j" class="ldet">{{ d.sym }} {{ d.rate ?? d.cooldown_sec ?? d.borrowed ?? d.reason ?? '' }}</div>
          </div>
        </div>
        <div class="fnote" style="margin-top:8px">灯=真数据源逐项判定(面板/意图账);N/A 灯=数据源待接,绝不装绿。裸债 P0 的实盘权威=coin naked_short_guard(0.5s)+risk-ledger R11,此处为面板口径速览。</div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import RiskStatusBar from '../../components/RiskStatusBar.vue'
import { mixApi } from '../../api/mix'

const tab = ref('push')
const ov = ref({}); const g = ref({}); const gates = ref([]); const cases = ref([])
const exp = ref(-1); const busy = ref('')
const form = ref({ symbol: '', source: '人工盯盘', reason: '', structure: '', amount: '',
  invalidation: '', review_by: '', tail_budget: '' })
const STATES = ['PENDING_BORROW', 'BORROWED_IDLE', 'OPEN', 'PENDING_REPAY', 'CLOSED', 'FAILED']
const STALE_ST = ['PENDING_BORROW', 'BORROWED_IDLE', 'PENDING_REPAY']
const gateOk = computed(() => gates.value.find(s => s.k === '风险闸')?.ok === true)
let t1 = null

async function load() {
  try { ov.value = await mixApi.c3Overview() } catch (e) { /* 状态条示 STALE */ }
  try { cases.value = ((await mixApi.aicoinLabList())?.rows || []).filter(c => c.action === 'PUSH_CASE' || c.product === 'C3.S').slice(0, 20) } catch (e) { /* */ }
}
async function brief() {
  if (!form.value.symbol) return
  try {
    const r = await mixApi.c3Brief(form.value.symbol)
    g.value = r?.grid || {}; gates.value = r?.gates || []
  } catch (e) { g.value = {}; gates.value = [] }
}
async function saveCase() {
  busy.value = 'case'
  try {
    await mixApi.aicoinLabSave({ symbol: form.value.symbol, action: 'PUSH_CASE', product: 'C3.S',
      structure: form.value.structure, stage: form.value.source, confidence: '人工',
      evidence_for: form.value.reason, invalidation: form.value.invalidation,
      review_by: form.value.review_by, tail_budget: form.value.tail_budget || form.value.amount })
    ElMessage.success('案件已登记(不进命令队列)')
    load()
  } catch (e) { ElMessage.error(e?.detail || '登记失败(字段必填)') } finally { busy.value = '' }
}
async function confirmPush() {
  busy.value = 'push'
  try {
    await ElMessageBox.confirm(`确认推送 ${form.value.symbol} 进 C3 引擎?coin 规则/黑名单/借币闸原样生效`, '操作员确认', { type: 'warning' })
    const extra = form.value.amount ? { amount: parseFloat(form.value.amount) } : {}
    await mixApi.coinMenu(form.value.symbol.toUpperCase(), { action: 'push_symbol', ...extra })
    ElMessage.success('已推送(coin 状态机执行,回执见坑位台)')
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '被拒绝') } finally { busy.value = '' }
}
onMounted(() => { load(); t1 = setInterval(load, 20000) })
onUnmounted(() => t1 && clearInterval(t1))
</script>

<style scoped lang="scss">
.c3 { display: flex; flex-direction: column; gap: 10px; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; min-width: 0; padding-bottom: 8px; }
.chd2 { font-size: 12px; font-weight: 700; color: var(--mix-t1, #EAECEF); padding: 10px 14px 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.grow { flex: 1; }
.dimtxt { color: var(--mix-t3, #5E6673); font-size: 10.5px; font-weight: 400; }
.pad { padding: 6px 14px; }
.bad { color: #F6465D
!important; }
.tri { display: grid; grid-template-columns: 380px minmax(0,1fr) 380px; gap: 10px;
  @media (max-width: 1500px) { grid-template-columns: 1fr; } }
.pf { padding: 0 14px; }
.btns { display: flex; gap: 8px; padding: 0 14px; }
.grid9 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 2px 14px 6px; }
.g { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 6px; padding: 7px 10px;
  display: flex; flex-direction: column; gap: 1px;
  span { font-size: 9.5px; color: var(--mix-t3, #5E6673); }
  b { font-size: 11.5px; color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.pipe { display: flex; gap: 6px; flex-wrap: wrap; padding: 0 14px; }
.pstep { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
  &.ok { background: rgba(14,203,129,.12); color: #35b57c; }
  &.bad2 { background: rgba(246,70,93,.16); color: #F6465D; }
  &.na { background: rgba(94,102,115,.15); color: var(--mix-t3, #5E6673); } }
.fnote { font-size: 10px; color: var(--mix-t3, #5E6673); padding: 6px 14px 0; }
.lrow { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--mix-t2, #848E9C);
  padding: 4px 14px; border-bottom: 1px dashed var(--mix-border, #262B33);
  b { color: var(--mix-t1, #EAECEF); } }
.legend { display: flex; gap: 5px; flex-wrap: wrap; font-weight: 400; }
.lg { font-style: normal; font-size: 9.5px; font-weight: 800; padding: 1px 6px; border-radius: 4px;
  background: rgba(94,102,115,.15); color: var(--mix-t2, #848E9C); }
.st-OPEN { background: rgba(14,203,129,.12); color: #35b57c; }
.st-PENDING_BORROW, .st-BORROWED_IDLE, .st-PENDING_REPAY { background: rgba(240,185,11,.14); color: #F0B90B; }
.st-FAILED { background: rgba(246,70,93,.16); color: #F6465D; }
.st-CLOSED { background: rgba(94,102,115,.15); color: var(--mix-t3, #5E6673); }
.lhead, .lrow2 { display: grid; grid-template-columns: 110px 100px 130px 90px 90px 90px 90px 110px 90px;
  font-size: 10.5px; align-items: center; padding: 0 14px; }
.lhead { color: var(--mix-t3, #5E6673); font-size: 10px; height: 22px; border-bottom: 1px solid var(--mix-border, #262B33); }
.lrow2 { height: 30px; border-bottom: 1px solid var(--mix-border, #262B33); color: var(--mix-t2, #848E9C); cursor: pointer;
  b { color: var(--mix-t1, #EAECEF); }
  &:hover, &.open { background: var(--mix-card2, #1E2329); }
  &.warn2 { background: rgba(240,185,11,.04); } }
.r { text-align: right; padding-right: 8px; font-variant-numeric: tabular-nums; }
.drawer { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 10px 20px;
  background: var(--mix-panel, #12151A); border-left: 2px solid #A78BFA; border-bottom: 1px solid var(--mix-border, #262B33);
  font-size: 11px; color: var(--mix-t2, #848E9C); }
.dh { font-size: 10px; color: var(--mix-t3, #5E6673); margin-bottom: 3px; font-weight: 700; }
.dline { padding: 2px 0; }
.lights { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
.light { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 10px; padding: 12px 14px;
  &.hot { border-color: rgba(246,70,93,.5); .ln { color: #F6465D; } }
  &.okl .ln { color: #35b57c; }
  &.na2 { opacity: .65; } }
.lk { font-size: 11px; color: var(--mix-t2, #848E9C); }
.ln { font-size: 22px; font-weight: 800; }
.ldet { font-size: 10.5px; color: var(--mix-t2, #848E9C); padding-top: 2px; }
</style>
