<template>
  <!-- REV2 §4A.6 客户与份额:从操作员管理切开——此处只有客户资金权益,不含操作角色/权限。
       登录身份≠操作权限≠查看范围≠投资份额;权益=Units×单位净值,不可直接编辑。 -->
  <div class="mixclients">
    <!-- 事实带(§4A.6):CORE_POOL 净值/总Units/已分配权益 -->
    <div class="factbar">
      <div class="fact"><span>已核定净值</span><b>{{ pool.nav_status || '—' }}</b></div>
      <div class="fact"><span>每份价值</span><b><ValueCell :value="pool.nav_per_unit" :dp="4" :state="pool.nav_per_unit==null?'NOT_YET_AVAILABLE':undefined"/></b></div>
      <div class="fact"><span>总份额</span><b><ValueCell :value="pool.total_units" :dp="2" :state="pool.total_units==null?'NOT_YET_AVAILABLE':undefined"/></b></div>
      <div class="fact"><span>已分配权益</span><b><ValueCell :value="pool.allocated_equity" suffix=" U" :dp="2" :state="pool.allocated_equity==null?'NOT_YET_AVAILABLE':undefined"/></b></div>
      <div class="fact"><span>数据截至</span><b class="dim">{{ (pool.as_of||'').replace('T',' ').slice(0,16) || '—' }}</b></div>
    </div>

    <div class="card">
      <div class="chd"><b>共池投资人（CORE_POOL）</b>
        <span class="sub">一户一受益主体 · 相同组合收益率、各自 Units 与权益 · 不复制策略/订单</span>
        <el-button size="small" style="margin-left:auto" @click="load">刷新</el-button></div>
      <div class="thead">
        <span class="c-name">客户名称</span><span class="c-portal">门户账号</span>
        <span class="c-num">持有份额</span><span class="c-num">份额占比</span>
        <span class="c-num">每份价值</span><span class="c-num">本人权益</span>
        <span class="c-st">状态</span><span class="c-act">操作</span>
      </div>
      <div v-for="c in core" :key="c.client_id" class="row">
        <span class="c-name"><b style="color:var(--mix-gold,#F0B90B)">{{ c.name }}</b></span>
        <span class="c-portal">
          <i v-if="c.portal_bound" class="tag ok">已绑定 {{ c.access_grants }}</i>
          <i v-else class="tag off">未绑定</i>
        </span>
        <span class="c-num"><ValueCell :value="c.units" :dp="2" :state="c.units?undefined:'ZERO'"/></span>
        <span class="c-num"><ValueCell :value="c.share_ratio!=null?c.share_ratio*100:null" suffix="%" :dp="1" :state="c.share_ratio==null?'NOT_YET_AVAILABLE':undefined"/></span>
        <span class="c-num"><ValueCell :value="c.nav_per_unit" :dp="4" :state="c.nav_per_unit==null?'NOT_YET_AVAILABLE':undefined"/></span>
        <span class="c-num"><ValueCell :value="c.equity_usdt" suffix=" U" :dp="2" :state="c.equity_usdt==null?'NOT_YET_AVAILABLE':undefined"/></span>
        <span class="c-st"><i class="tag" :class="c.share_account_ready?'ok':'wait'">{{ c.share_account_ready?'已配置':'待配置' }}</i></span>
        <span class="c-act">
          <el-button size="small" text @click="openGrant(c)">绑定查看账号</el-button>
          <el-button size="small" text type="success" @click="openCapital(c,'SUBSCRIBE')">申购</el-button>
          <el-button size="small" text type="warning" @click="openCapital(c,'REDEEM')">赎回</el-button>
        </span>
      </div>
      <div v-if="!core.length" class="empty">暂无共池投资人</div>
      <div class="fnote">份额权威=mix_main 份额账本(未搬 dcm_main);<b>不提供直接修改权益/份额比例</b>——只能经 申购/赎回 走 FINALIZED NAV + DRY_RUN + Passkey 的可审计闭环。停用登录不改变受益权。</div>
    </div>

    <div class="card" v-if="sma.length">
      <div class="chd"><b>SMA 大客户（独立账户）</b><span class="sub">独立 NAV,不使用共池份额</span></div>
      <div v-for="c in sma" :key="c.client_id" class="row">
        <span class="c-name"><b style="color:var(--mix-gold,#F0B90B)">{{ c.name }}</b></span>
        <span class="c-portal"><i class="tag" :class="c.portal_bound?'ok':'off'">{{ c.portal_bound?'已绑定':'未绑定' }}</i></span>
        <span class="c-num dim" style="grid-column:span 4">独立账户,不使用共池份额（NAV/流水在客户详情）</span>
        <span class="c-st"><i class="tag wait">演示占位</i></span>
        <span class="c-act">—</span>
      </div>
    </div>

    <!-- 申购/赎回可审计闭环(§4A.5:登记→DRY_RUN前后→Passkey→过账→重建投影) -->
    <div class="card">
      <div class="chd"><b>申赎流水（可审计 · 更正只新增 REVERSAL 不删历史）</b>
        <el-button size="small" style="margin-left:auto" @click="loadCr">刷新</el-button></div>
      <div class="thead cr"><span>时间</span><span>客户</span><span>类型</span><span>金额/份额</span><span>状态</span><span>流水号</span><span>操作</span></div>
      <div v-for="r in crs" :key="r.id" class="row cr">
        <span class="dim">{{ (r.created_at||'').slice(5,16) }}</span>
        <span>{{ nameOf(r.client_id) }}</span>
        <span><i class="tag" :class="r.request_type==='SUBSCRIBE'?'ok':'wait'">{{ r.request_type==='SUBSCRIBE'?'申购':'赎回' }}</i></span>
        <span class="amtx">{{ r.amount_usdt!=null ? r.amount_usdt+' U' : (r.units!=null ? r.units+' 份' : '—') }}</span>
        <span><i class="tag" :class="r.status==='POSTED'?'ok':r.status==='REVERSED'?'off':'wait'">{{ CR_ST[r.status]||r.status }}</i></span>
        <span class="dim ell">{{ r.external_flow_id || '—' }}</span>
        <span><el-button v-if="r.status==='POSTED' && r.posted_event_id" size="small" text type="danger" @click="doReverse(r)">冲正</el-button></span>
      </div>
      <div v-if="!crs.length" class="empty">暂无申赎流水</div>
    </div>

    <el-dialog v-model="cap.open" :title="`${cap.type==='SUBSCRIBE'?'申购':'赎回'} · ${cap.name}`" width="520px">
      <el-steps :active="cap.step" simple style="margin-bottom:14px">
        <el-step title="登记申请"/><el-step title="预演前后"/><el-step title="Passkey过账"/>
      </el-steps>
      <div v-if="cap.step===0">
        <el-form label-width="110px" size="small">
          <el-form-item v-if="cap.type==='SUBSCRIBE'" label="实缴金额U"><el-input-number v-model="cap.amount" :min="0" style="width:100%"/>
            <div class="hint">资金确认到账后按最新 FINALIZED NAV 折算 Units;未到账不发份额。</div></el-form-item>
          <el-form-item v-else label="赎回份额"><el-input-number v-model="cap.units" :min="0" style="width:100%"/>
            <div class="hint">赎回不超过持有;定价按截止规则的 FINALIZED NAV。</div></el-form-item>
        </el-form>
        <div class="cbtns"><el-button type="primary" :disabled="cap.type==='SUBSCRIBE'?!cap.amount:!cap.units" @click="crCreate">登记并预演</el-button></div>
      </div>
      <div v-else-if="cap.step===1 && cap.dry">
        <div class="dry">
          <div class="drow"><span>单位净值</span><b>{{ cap.dry.nav_per_unit }} <i class="dim">({{ cap.dry.nav_status }})</i></b></div>
          <div class="drow head"><span></span><span>操作前</span><span>操作后</span></div>
          <div class="drow"><span>持有份额</span><b>{{ cap.dry.before.units }}</b><b class="gold">{{ cap.dry.after.units }}</b></div>
          <div class="drow"><span>份额占比</span><b>{{ cap.dry.before.ratio ?? '—' }}%</b><b class="gold">{{ cap.dry.after.ratio ?? '—' }}%</b></div>
          <div class="drow"><span>本人权益</span><b>{{ cap.dry.before.equity }} U</b><b class="gold">{{ cap.dry.after.equity }} U</b></div>
          <div class="drow"><span>变动份额</span><b :class="Number(cap.dry.delta_units)>=0?'up':'dn'">{{ cap.dry.delta_units }}</b></div>
        </div>
        <el-form label-width="110px" size="small" style="margin-top:10px">
          <el-form-item label="资金流水号"><el-input v-model="cap.flow" placeholder="真实入金/出金凭证(external_flow_id)"/>
            <div class="hint">过账须关联真实资金流水;操作员不能自选对某人有利的历史净值。</div></el-form-item>
        </el-form>
        <div class="cbtns"><el-button @click="cap.step=0">返回</el-button>
          <el-button type="warning" :disabled="!cap.flow" :loading="cap.busy" @click="doPost">Passkey 认证并过账</el-button></div>
      </div>
      <div v-else-if="cap.step===2" class="done">
        <p><b>已过账</b> · 事件 #{{ cap.result?.event_id }} · {{ cap.result?.event_type }} {{ cap.result?.units }} 份</p>
        <p class="dim">投影已重建,门户即时反映。更正只能新增 REVERSAL 事实,不覆盖历史。</p>
        <div class="cbtns"><el-button type="primary" @click="cap.open=false">完成</el-button></div>
      </div>
    </el-dialog>
    <el-dialog v-model="grantDlg.open" title="绑定查看账号（授予组合查看权限）" width="440px">
      <p class="dlgnote">授权 ≠ 操作权限:被授权的登录账号只能只读本客户组合收益,不获得任何操作能力。</p>
      <el-form label-width="120px" size="small">
        <el-form-item label="客户"><b>{{ grantDlg.name }}</b></el-form-item>
        <el-form-item label="登录账号">
          <el-select v-model="grantDlg.subj" filterable placeholder="选择系统现有账号" style="width:100%">
            <el-option v-for="u in systemUsers" :key="u.id"
                       :label="`${u.operator} (ID:${u.id})`" :value="u.id"/>
          </el-select>
          <div class="hint">该账号登录 user.hustle2026.xyz 门户即可查看本客户收益。</div></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grantDlg.open=false">取消</el-button>
        <el-button type="warning" :disabled="!grantDlg.subj" @click="doGrant">授予查看权限（需 SUPER_ADMIN）</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { onMounted, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'
import { passkeyTicket } from '../../api/passkey'
import ValueCell from '../../components/v62/ValueCell.vue'
const clients = ref([]); const pool = ref({})
const core = computed(() => clients.value.filter(c => c.client_type === 'CORE_POOL'))
const sma = computed(() => clients.value.filter(c => c.client_type === 'SMA'))
const grantDlg = ref({ open: false, id: null, name: '', subj: null })
const systemUsers = ref([])
async function load() {
  try { const r = await mixApi.clientsList(); clients.value = r.clients || []; pool.value = r.pool || {} }
  catch (e) { ElMessage.error(e?.detail || '加载失败') }
}
async function loadSystemUsers() {
  try { const r = await mixApi.operatorsList(); systemUsers.value = r.operators || [] }
  catch (e) { /* 降级:保留手输模式 */ }
}
function openGrant(c) {
  grantDlg.value = { open: true, id: c.client_id, name: c.name, subj: null }
  if (!systemUsers.value.length) loadSystemUsers()
}
// 申赎闭环
const cap = ref({ open: false, step: 0, type: '', client_id: null, name: '', amount: 0, units: 0, reqId: null, dry: null, flow: '', busy: false, result: null })
function openCapital(c, type) {
  cap.value = { open: true, step: 0, type, client_id: c.client_id, name: c.name, amount: 0, units: 0, reqId: null, dry: null, flow: '', busy: false, result: null }
}
async function crCreate() {
  try {
    const b = { client_id: cap.value.client_id, request_type: cap.value.type }
    if (cap.value.type === 'SUBSCRIBE') b.amount_usdt = cap.value.amount; else b.units = cap.value.units
    const r = await mixApi.crCreate(b); cap.value.reqId = r.request_id
    cap.value.dry = await mixApi.crDryRun(r.request_id); cap.value.step = 1
  } catch (e) { ElMessage.error(e?.detail || '登记失败') }
}
async function doPost() {
  cap.value.busy = true
  try {
    const ticket = await passkeyTicket()
    cap.value.result = await mixApi.crPost(cap.value.reqId, { reauth_ticket: ticket, external_flow_id: cap.value.flow })
    cap.value.step = 2; load(); loadCr()
  } catch (e) { ElMessage.error(e?.detail || e?.message || 'Passkey 认证失败或过账被拒') } finally { cap.value.busy = false }
}
// 申赎流水 + 冲正
const crs = ref([])
const CR_ST = { CREATED: '待过账', FUNDS_CONFIRMED: '资金已确认', POSTED: '已过账', REVERSED: '已冲正', CANCELLED: '已取消' }
function nameOf(cid) { const c = clients.value.find(x => x.client_id === cid); return c ? c.name : ('#' + cid) }
async function loadCr() { try { crs.value = await mixApi.crList() } catch (e) { crs.value = [] } }
async function doReverse(r) {
  try {
    const { value: reason } = await ElMessageBox.prompt(`冲正「${nameOf(r.client_id)}」的 ${r.request_type==='SUBSCRIBE'?'申购':'赎回'}（新增 REVERSAL，历史不删）。填冲正原因：`, '冲正确认', { inputPlaceholder: '如:资金未实际到账/录错金额' })
    const ticket = await passkeyTicket()
    await mixApi.shareEventReverse(r.posted_event_id, { reauth_ticket: ticket, reason })
    ElMessage.success('已冲正并重建投影'); loadCr(); load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.message || '冲正失败') }
}
async function doGrant() {
  try {
    await mixApi.clientGrant(grantDlg.value.id, { action: 'grant', auth_subject_id: grantDlg.value.subj })
    ElMessage.success('已授予查看权限（门户登录即生效）'); grantDlg.value.open = false; load()
  } catch (e) { ElMessage.error(e?.detail || '失败（需 SUPER_ADMIN）') }
}
onMounted(() => { load(); loadCr() })
</script>
<style scoped>
.mixclients { display: flex; flex-direction: column; gap: 12px; }
.factbar { display: flex; gap: 22px; flex-wrap: wrap; background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 12px 18px; }
.fact { display: flex; flex-direction: column; gap: 2px; }
.fact span { font-size: 10px; color: var(--mix-t3, #5E6673); }
.fact b { font-size: 14px; color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; }
.fact b.dim { font-size: 12px; color: var(--mix-t2, #848E9C); font-weight: 400; }
.card { background: var(--mix-card, #181B21); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 14px 16px; }
.chd { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px;
  b { font-size: 13px; } .sub { font-size: 10.5px; color: var(--mix-t3, #5E6673); } }
.thead, .row { display: grid; grid-template-columns: 120px 110px 100px 88px 90px 110px 80px 1fr; align-items: center; gap: 8px; padding: 0 6px; }
.thead.cr, .row.cr { grid-template-columns: 96px 90px 70px 110px 90px 1fr 70px; }
.ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thead { font-size: 10px; color: var(--mix-t3, #5E6673); height: 24px; border-bottom: 1px solid var(--mix-border, #262B33); }
.row { min-height: 34px; font-size: 12px; color: var(--mix-t2, #848E9C); border-bottom: 1px solid var(--mix-border, #262B33); }
.row b { color: var(--mix-t1, #EAECEF); }
.c-num { text-align: right; font-variant-numeric: tabular-nums; }
.dim { color: var(--mix-t3, #5E6673); }
.tag { font-style: normal; font-size: 9.5px; padding: 1px 6px; border-radius: 3px; border: 1px solid var(--mix-border, #262B33); }
.tag.ok { color: #35b57c; border-color: #35b57c66; }
.tag.off { color: var(--mix-t3, #5E6673); }
.tag.wait { color: #F0B90B; border-color: #F0B90B55; }
.empty { padding: 24px 0; text-align: center; color: var(--mix-t3, #5E6673); font-size: 12px; }
.fnote { font-size: 10.5px; color: var(--mix-t3, #5E6673); margin-top: 10px; line-height: 1.6; }
.dlgnote { font-size: 11px; color: #F0B90B; margin-bottom: 12px; }
.hint { font-size: 10px; color: var(--mix-t3, #5E6673); margin-top: 4px; line-height: 1.5; }
.cbtns { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.dry { background: var(--mix-panel, #12151A); border: 1px solid var(--mix-border, #262B33); border-radius: 8px; padding: 10px 14px; }
.drow { display: grid; grid-template-columns: 90px 1fr 1fr; align-items: center; font-size: 12px; padding: 4px 0; color: var(--mix-t2, #848E9C);
  b { color: var(--mix-t1, #EAECEF); font-variant-numeric: tabular-nums; text-align: right; } b.gold { color: #F0B90B; } b.up { color: #0ECB81; } b.dn { color: #F6465D; } }
.drow.head { font-size: 10px; color: var(--mix-t3, #5E6673); border-bottom: 1px solid var(--mix-border, #262B33); }
.drow.head span:not(:first-child) { text-align: right; }
.dim { color: var(--mix-t3, #5E6673); font-weight: 400; }
.done { text-align: center; padding: 20px 0; b { color: #35b57c; } p { margin: 6px 0; font-size: 13px; color: var(--mix-t1, #EAECEF); } p.dim { font-size: 11px; color: var(--mix-t3, #5E6673); } }
.crow .c-num, .fact b{color:#7DE3F4}
</style>
