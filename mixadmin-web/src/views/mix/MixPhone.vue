<template>
  <!-- V6.1 §8.3 手机操作员专属壳(OPERATOR_MOBILE_LIMITED):待办|机会|持仓|风险|更多。
       只渲染服务端白名单动作;快照过期/断网=显示最后快照+禁发命令;无 SW 不缓存敏感数据。 -->
  <div class="mphone" v-if="authed">
    <div class="mtop">
      <b>Mix 值守</b>
      <span class="gen" :class="{bad:stale}">{{ stale ? '数据过期·只读' : 'G'+(snap?.generation??'—')+' · '+ago }}</span>
    </div>
    <div v-if="offline" class="offbar"><FIcon name="offline" :size="12"/> 网络中断 · 显示最后快照 · 命令不会离线排队</div>
    <div v-else-if="stale" class="offbar warn"><FIcon name="clock" :size="12"/> 快照过期(>90s) · 已自动禁止新增风险,减险不受影响</div>

    <!-- 待办 -->
    <div class="mbody" v-show="ptab==='todo'">
      <div v-if="p0" class="pcard p0c">
        <b>P0 · {{ p0.venue }} {{ p0.title || p0.rule }}</b>
        <span>{{ (p0.detail||'').slice(0,80) }}</span>
        <button class="pbtn danger" :disabled="stale||pausing" @click="pauseNew"><FIcon name="pause" :size="12"/> 暂停开新仓(减险·立即)</button>
      </div>
      <div v-for="w in abnormal" :key="w.work_item_id" class="pcard">
        <b>{{ w.symbol }} · {{ w.stage_detail }}</b>
        <span>{{ w.next_action }}</span>
        <div class="prow2">
          <button v-for="a in w.allowed_actions" :key="a.code" class="pbtn" :class="{danger:a.kind==='danger'}"
                  :disabled="stale||!a.wired" @click="act(w,a)">{{ a.label }}</button>
        </div>
      </div>
      <div v-if="opps.length" class="pcard oppnote">
        <b>◎ 有 {{ opps.length }} 个过闸候选</b>
        <span class="dim3">机会评估与开仓请在桌面完成(手机角色仅减险/确认);最优:{{ opps[0]?.symbol }} {{ evT(opps[0]) }}</span>
      </div>
      <div v-if="!p0 && !abnormal.length" class="pempty"><FIcon name="check" :size="13"/> 无待办 · 系统自动运行中</div>
    </div>
    <!-- 研判(REV2 §9.4:受信手机可研判/看K线横屏/开完整研判) -->
    <div class="mbody" v-show="ptab==='research'">
      <div class="pcard oppnote">
        <b>候选研判 · {{ opps.length }} 过闸</b>
        <span class="dim3">{{ dev.state==='trusted' ? '本机受信:可研判并生成计划(额度内,经预演+Passkey)' : '本机未受信:仅查看K线与官方数据,开仓请在受信桌面/设备' }}</span>
      </div>
      <div v-for="o in opps" :key="o.work_item_id" class="pcard rcard" @click="openKline(o.symbol)">
        <b>{{ o.symbol }} · {{ o.strategy_code }} <span class="ev" :class="(o.expected_net_return||0)>=0?'up2':'dn'">{{ evT(o) }}</span></b>
        <span class="dim3">建议 {{ o.capital_reserved?kU(o.capital_reserved):'—' }} · 风险 {{ o.risk_status?.level==='NORMAL'?'低':(o.risk_status?.level||'—') }} · 点看K线横屏</span>
      </div>
      <div v-if="!opps.length" class="pempty"><FIcon name="check" :size="13"/> 暂无过闸候选</div>
      <div class="rbtns">
        <button class="pbtn w" @click="openResearch('')">打开完整研判工作台 →</button>
      </div>
    </div>
    <!-- K线横屏全屏层 -->
    <div v-if="kl.open" class="klfull" @click.self="kl.open=false">
      <div class="klbar">
        <b>{{ kl.symbol }}</b>
        <span class="klp"><i v-for="p in KPERIODS" :key="p.v" :class="{on:kl.period===p.v}" @click="kl.period=p.v;loadKline()">{{ p.t }}</i></span>
        <span class="klclose" @click="kl.open=false"><FIcon name="x" :size="18"/></span>
      </div>
      <div ref="klEl" class="klchart"></div>
      <div class="klft">
        <span class="dim3">{{ kl.note }} · 横置手机看更清</span>
        <button class="pbtn" @click="openResearch(kl.symbol)">在完整研判中生成计划 →</button>
      </div>
    </div>
    <!-- 持仓 -->
    <div class="mbody" v-show="ptab==='pos'">
      <div v-for="w in positions" :key="w.work_item_id" class="pcard" @click="psel=psel===w.work_item_id?'':w.work_item_id">
        <b>{{ w.symbol }} · {{ w.strategy_code }} <i class="stg">{{ w.stage_detail }}</i>
          <i v-if="w.risk_protection_state && w.risk_protection_state!=='NORMAL'" class="prot" :class="w.risk_protection_state"><FIcon name="shield" :size="9"/>{{ PROT_CN[w.risk_protection_state]||w.risk_protection_state }}</i></b>
        <span>投入 {{ kU(w.capital_reserved) }} · 已确认 {{ dvT(w.confirmed_pnl, w.data_state?.confirmed_pnl) }} · {{ w.next_deadline||'' }}</span>
        <span v-if="w.risk_protection_state && w.risk_protection_state!=='NORMAL'" class="dn">点差保护(shadow):真实退出 {{ w.closeout_pnl_net??'—' }}U · 预算余 {{ w.hard_loss_budget_remaining??'—' }}U</span>
        <div class="prow2" v-if="psel===w.work_item_id">
          <button v-for="a in w.allowed_actions" :key="a.code" class="pbtn" :class="{danger:a.kind==='danger'}"
                  :disabled="stale||!a.wired" @click.stop="act(w,a)">{{ a.label }}</button>
        </div>
      </div>
      <div v-if="!positions.length" class="pempty">无在管组合</div>
    </div>
    <!-- 风险 -->
    <div class="mbody" v-show="ptab==='risk'">
      <div class="pcard"><b>允许操作</b><span :class="canOpen?'up':'dn'">{{ snap?.effective_capabilities?.can_open ? '全部(正常运行)' : '减险类('+(snap?.effective_capabilities?.reason||'受限')+')' }}</span></div>
      <div v-for="i in (snap?.incidents||[])" :key="i.venue+i.rule" class="pcard">
        <b :class="i.severity==='fatal'?'dn':''">{{ i.severity==='fatal'?'P0':'P1' }} · {{ i.venue }} {{ i.title }}</b>
        <span>{{ (i.detail||'').slice(0,80) }} · 命中{{ i.hit_count }}次</span>
      </div>
      <div v-if="protHotN" class="pcard"><b class="dn"><FIcon name="shield" :size="11"/> 点差保护 · {{ protHotN }} 项越线(shadow)</b>
        <span class="dim3">{{ protNote }} · 减仓/退出决策仍人工;手机可预览+暂停新增</span></div>
      <div v-if="!(snap?.incidents||[]).length && !protHotN" class="pempty"><FIcon name="check" :size="13"/> 无活跃风险事件</div>
      <button class="pbtn danger w" :disabled="stale||pausing" @click="pauseNew"><FIcon name="pause" :size="12"/> 暂停开新仓(全局·减险)</button>
    </div>
    <!-- 更多 -->
    <div class="mbody" v-show="ptab==='more'">
      <!-- REV2 §9 受信设备:决定本机能否完整研判/开仓(受信+额度内),否则只读/减险 -->
      <div class="pcard">
        <b>本机受信状态 <i class="dtag" :class="dev.state">{{ {trusted:'已受信',untrusted:'未受信'}[dev.state]||dev.state }}</i></b>
        <span v-if="dev.state==='trusted'" class="dim3">可完成研判/计划/预演/Passkey 开仓,受设备额度约束(单笔≤{{ dev.limits?.GLOBAL?.max_notional ?? '—' }}U · 当日≤{{ dev.limits?.GLOBAL?.daily_budget ?? '—' }}U);额度只能在受信桌面调整。</span>
        <span v-else class="dim3">本机未受信:只读+确认告警+暂停新增。开仓须先在受信桌面「操作员管理·受信设备」注册本机会话。</span>
        <div v-if="dev.state!=='trusted'" class="devreg">
          <input v-model="devSid" class="pinp" placeholder="粘贴受信桌面生成的设备会话" />
          <button class="pbtn" @click="bindDevice">绑定本机</button>
        </div>
        <button v-else class="pbtn danger" @click="unbindDevice">解绑本机(仅清本地会话)</button>
      </div>
      <div class="pcard"><b>手机能力(服务端强制)</b>
        <span class="dim3">受信:研判/生成计划/预演/Passkey 开仓(额度内)+减险<br/>未受信:确认告警/暂停新增/撤单减仓(带预演)<br/>任何设备禁:提额/改规则/恢复正常/凭证/资金动作</span></div>
      <div class="pcard"><b>安全</b><span class="dim3">开仓/减险=计划→预演→Passkey;快照过期禁新增;命令绝不离线排队;设备丢失可在桌面立即撤销。</span></div>
      <button class="pbtn w" @click="logout">退出登录</button>
    </div>

    <div class="mtabs">
      <div v-for="t in PTABS" :key="t.k" class="mt" :class="{on:ptab===t.k}" @click="ptab=t.k">
        <span><FIcon :name="t.i" :size="18"/></span>{{ t.t }}
        <i v-if="t.k==='todo'&&todoN" class="pd">{{ todoN }}</i>
      </div>
    </div>
    <ClosePreviewDialog v-model="closeDlg.open" :symbol="closeDlg.symbol"/>
    <PartialRepayModal v-model="repayDlg.open" :symbol="repayDlg.symbol"/>
  </div>
  <div v-else class="mgate">
    <b>Mix 手机值守</b>
    <input v-model="lg.u" placeholder="用户名"/><input v-model="lg.p" type="password" placeholder="密码"/>
    <button class="pbtn w" @click="doLogin">登录(受限操作员)</button>
    <span class="dim3">{{ lgErr }}</span>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { mixApi } from '../../api/mix'
import { useV6Snapshot } from '../../composables/useV6'
import ClosePreviewDialog from '../../components/ClosePreviewDialog.vue'
import PartialRepayModal from '../../components/rules/PartialRepayModal.vue'

const router = useRouter()
const { snap, stale, canOpen, ago } = useV6Snapshot()
// V6.2 §九 / REV2 §9.4:受信手机可完整研判——五页签 待办|研判|持仓|风险|更多
const PTABS = [{ k: 'todo', t: '待办', i: 'inbox' }, { k: 'research', t: '研判', i: 'flask' },
  { k: 'pos', t: '持仓', i: 'list' }, { k: 'risk', t: '风险', i: 'shield' }, { k: 'more', t: '更多', i: 'more' }]
const ptab = ref('todo')
const psel = ref('')
const pausing = ref(false)
const offline = ref(!navigator.onLine)
const closeDlg = ref({ open: false, symbol: '' })
const repayDlg = ref({ open: false, symbol: '' })
const authed = ref(!!localStorage.getItem('mix_token'))
const lg = ref({ u: '', p: '' }); const lgErr = ref('')
const items = ref([])

const opps = computed(() => items.value.filter(w => w.workflow_stage === 'DISCOVERED'))
const positions = computed(() => items.value.filter(w => ['RESERVED','EXECUTING','HOLDING','EXITING'].includes(w.workflow_stage)))
const abnormal = computed(() => items.value.filter(w => w.workflow_stage === 'RECONCILING'))
const p0 = computed(() => (snap.value?.incidents || []).find(i => i.severity === 'fatal') || null)
const todoN = computed(() => abnormal.value.length + (p0.value ? 1 : 0))
// §8 点差保护(shadow):与桌面同源 risk_exit_summary
const PROT_CN = { WATCH: '观察', NO_ADD: '禁加仓', REDUCE_REQUIRED: '需减仓', EXIT_REQUIRED: '需退出' }
const protHotN = computed(() => { const c = snap.value?.risk_exit_summary?.counts || {}; return (c.NO_ADD||0)+(c.REDUCE_REQUIRED||0)+(c.EXIT_REQUIRED||0) })
// REV2 §9 受信设备:bootstrap 返回本机受信态+额度(据 X-Device-Session)
const dev = ref({ state: 'untrusted', limits: null })
const devSid = ref('')
async function loadDevice() {
  try { const b = await mixApi.v6Bootstrap('phone'); dev.value = b.device_trust || { state: 'untrusted' } } catch (e) { /* 未登录/不可达 */ }
}
function bindDevice() {
  const s = devSid.value.trim(); if (!s) { ElMessage.warning('请粘贴设备会话'); return }
  localStorage.setItem('mix_device_session', s); ElMessage.success('已绑定本机,重新校验受信态'); devSid.value = ''; loadDevice()
}
function unbindDevice() { localStorage.removeItem('mix_device_session'); dev.value = { state: 'untrusted', limits: null }; ElMessage.success('已解绑本机会话') }
// 研判:K线横屏 + 打开完整研判
const KPERIODS = [{ v: '15', t: '15m' }, { v: '60', t: '1h' }, { v: '240', t: '4h' }, { v: '1440', t: '1D' }]
const kl = ref({ open: false, symbol: '', period: '60', note: '', dbKey: '' })
const klEl = ref(null)
let klChart = null
function openResearch(sym) { router.push({ path: '/mix/aicoin', query: sym ? { symbol: sym } : {} }) }
async function openKline(sym) {
  kl.value = { open: true, symbol: sym, period: '60', note: '加载中…', dbKey: '' }
  await nextTick()
  if (!klChart && klEl.value) klChart = echarts.init(klEl.value)
  // 先取 canonical→AiCoin 映射(research/context 带 db_key)
  try { const ctx = await mixApi.researchContext(sym, 'C2.P'); kl.value.dbKey = ctx?.aicoin?.db_key || '' } catch (e) { /* */ }
  loadKline()
}
async function loadKline() {
  if (!klChart) { await nextTick(); if (klEl.value) klChart = echarts.init(klEl.value) }
  const dk = kl.value.dbKey
  if (!dk) { kl.value.note = '该币 AiCoin 图表未匹配'; return }
  try {
    const r = await mixApi.aicoinKline(dk, kl.value.period, 240)
    const rows = r?.data || []
    if (!rows.length) { kl.value.note = '无K线数据'; return }
    const norm = rows.map(k => Array.isArray(k)
      ? { t: +k[0] * (String(k[0]).length < 13 ? 1000 : 1), o: +k[1], h: +k[2], l: +k[3], c: +k[4] }
      : { t: +(k.ts || k.time || k.id) * 1000, o: +k.open, h: +k.high, l: +k.low, c: +k.close })
    kl.value.note = `${norm.length} 根 · 收 ${norm[norm.length - 1].c}`
    klChart.setOption({
      backgroundColor: 'transparent',
      grid: { left: 46, right: 8, top: 8, bottom: 22 },
      xAxis: { type: 'category', data: norm.map(k => new Date(k.t).toLocaleString('zh', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })), axisLabel: { color: '#5E6673', fontSize: 9 }, axisLine: { lineStyle: { color: '#262B33' } } },
      yAxis: { scale: true, splitLine: { lineStyle: { color: '#1E2329' } }, axisLabel: { color: '#5E6673', fontSize: 9 } },
      dataZoom: [{ type: 'inside', start: 45, end: 100 }],
      series: [{ type: 'candlestick', data: norm.map(k => [k.o, k.c, k.l, k.h]), itemStyle: { color: '#0ECB81', color0: '#F6465D', borderColor: '#0ECB81', borderColor0: '#F6465D' } }],
    })
    klChart.resize()
  } catch (e) { kl.value.note = 'K线拉取失败' }
}
const protNote = computed(() => { const c = snap.value?.risk_exit_summary?.counts || {}; return Object.entries(c).filter(([k])=>k!=='NORMAL').map(([k,v])=>`${PROT_CN[k]||k}${v}`).join(' · ') })

function evT(w) { const v = w.expected_net_return; return v == null ? '—' : `${v>=0?'+':''}${Number(v).toFixed(1)}bps/日` }
function kU(v) { if (v == null) return '未接入'; const n = Number(v); return n >= 1000 ? (n/1000).toFixed(1)+'K U' : n.toFixed(0)+' U' }
function dvT(v, st) { if (v != null) return `${v>=0?'+':''}${Number(v).toFixed(1)}U`; return { NOT_CONNECTED:'未接入', NOT_YET_AVAILABLE:'待产生' }[st] || '—' }
function oppActs(w) { return (w.allowed_actions||[]).filter(a => a.code !== 'opportunity_to_workbench') }
async function loadItems() {
  try { items.value = (await mixApi.v6WorkItems())?.items || [] } catch (e) { /* 保留最后数据 */ }
}
async function act(w, a) {
  if (stale.value || offline.value) { ElMessage.warning('快照过期/离线,命令不会发送'); return }
  switch (a.code) {
    case 'close_preview': closeDlg.value = { open: true, symbol: w.symbol }; return
    case 'c3_partial_repay': repayDlg.value = { open: true, symbol: w.symbol }; return
    case 'goto_risk_center': ptab.value = 'risk'; return
    case 'view': case 'view_basis': psel.value = w.work_item_id; return
  }
  try {
    const r = await mixApi.v6Command({ command_type: a.code, params: { symbol: w.symbol, strategy_code: w.strategy_code, work_item_id: w.work_item_id } })
    ElMessage.success(r?.result?.note || '已提交')
    loadItems()
  } catch (e) { ElMessage.error(e?.detail || '被拒绝(服务端白名单)') }
}
async function pauseNew() {
  pausing.value = true
  try { await mixApi.v6Command({ command_type: 'pause_new_risk', params: { reason: '手机值守:暂停新增' } }); ElMessage.success('已提交暂停新增') }
  catch (e) { ElMessage.error(e?.detail || '失败') } finally { pausing.value = false }
}
async function doLogin() {
  try {
    const r = await mixApi.login(lg.value.u, lg.value.p)
    localStorage.setItem('mix_token', r.access_token)
    authed.value = true; loadItems()
  } catch (e) { lgErr.value = '登录失败:' + (e?.detail || '账号或密码错误') }
}
function logout() { localStorage.removeItem('mix_token'); authed.value = false }
const onNet = () => { offline.value = !navigator.onLine }
let poll = null
onMounted(() => { loadItems(); loadDevice(); poll = setInterval(loadItems, 20000)
  window.addEventListener('online', onNet); window.addEventListener('offline', onNet) })
onBeforeUnmount(() => { clearInterval(poll)
  window.removeEventListener('online', onNet); window.removeEventListener('offline', onNet)
  try { klChart && klChart.dispose() } catch (e) { /* */ } })
</script>
<style scoped>
.mphone{min-height:100vh;background:var(--mix-bg,#0B0E11);display:flex;flex-direction:column;
  padding-bottom:calc(58px + env(safe-area-inset-bottom))}
.mtop{height:44px;background:var(--mix-panel,#12151A);border-bottom:1px solid var(--mix-border,#2B3139);
  display:flex;align-items:center;justify-content:space-between;padding:0 12px;position:sticky;top:0;z-index:5}
.mtop b{color:var(--mix-t1,#EAECEF);font-size:14px}
.gen{font-size:10px;color:var(--mix-t3,#5E6673)}
.gen.bad{color:#F6465D}
.offbar{background:#F6465D22;color:#F6465D;font-size:11px;padding:6px 12px;text-align:center}
.offbar.warn{background:#F0B90B22;color:#F0B90B}
.mbody{flex:1;padding:10px 12px;display:flex;flex-direction:column;gap:8px;overflow:auto}
.pcard{background:var(--mix-card,#181B21);border:1px solid var(--mix-border,#2B3139);border-radius:8px;
  padding:10px 12px;display:flex;flex-direction:column;gap:4px}
.pcard.p0c{border-color:#F6465D66;background:#F6465D0D}
.pcard b{font-size:13px;color:var(--mix-t1,#EAECEF)}
.pcard span{font-size:11px;color:var(--mix-t2,#848E9C)}
.pcard .stg{font-style:normal;font-size:10px;color:#F0B90B;margin-left:6px}
.prot{font-style:normal;font-size:9px;margin-left:6px;padding:0 5px;border-radius:3px}
.prot.WATCH{color:#F0B90B;border:1px solid #F0B90B66}
.prot.NO_ADD{color:#FF8A3D;border:1px solid #FF8A3D88}
.prot.REDUCE_REQUIRED,.prot.EXIT_REQUIRED{color:#F6465D;border:1px solid #F6465D88}
.dtag{font-style:normal;font-size:9px;margin-left:6px;padding:1px 6px;border-radius:3px;border:1px solid var(--mix-border,#2B3139)}
.dtag.trusted{color:#35b57c;border-color:#35b57c66}
.dtag.untrusted{color:#F0B90B;border-color:#F0B90B55}
.devreg{display:flex;gap:6px;margin-top:6px}
.pinp{flex:1;min-height:36px;background:var(--mix-panel,#12151A);border:1px solid var(--mix-border,#2B3139);border-radius:7px;color:var(--mix-t1,#EAECEF);padding:0 10px;font-size:12px}
.rcard{cursor:pointer}
.rcard .ev{font-size:11px;margin-left:6px}
.rcard .ev.up2{color:#0ECB81}.rcard .ev.dn{color:#F6465D}
.rbtns{padding:8px 0}
.klfull{position:fixed;inset:0;z-index:100;background:#0B0E11;display:flex;flex-direction:column}
.klbar{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--mix-border,#2B3139)}
.klbar b{color:var(--mix-t1,#EAECEF);font-size:15px}
.klp{display:flex;gap:4px;margin-left:auto}
.klp i{font-style:normal;font-size:11px;color:var(--mix-t3,#5E6673);padding:3px 8px;border-radius:5px;border:1px solid var(--mix-border,#2B3139)}
.klp i.on{color:#F0B90B;border-color:#F0B90B66}
.klclose{color:var(--mix-t2,#848E9C);padding:2px 4px}
.klchart{flex:1;min-height:0}
.klft{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 14px calc(8px + env(safe-area-inset-bottom));border-top:1px solid var(--mix-border,#2B3139)}
.klft .pbtn{min-height:34px}
.up{color:#0ECB81!important}.dn{color:#F6465D!important}
.dim3{font-size:10px;color:var(--mix-t3,#5E6673);line-height:1.5}
.prow2{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.pbtn{min-height:38px;padding:0 12px;border-radius:7px;border:1px solid var(--mix-border,#2B3139);
  background:var(--mix-card2,#20242C);color:var(--mix-t1,#EAECEF);font-size:12px;font-weight:700}
.pbtn.danger{background:#F6465D14;border-color:#F6465D66;color:#F6465D}
.pbtn.w{width:100%}
.pbtn:disabled{opacity:.4}
.pempty{padding:36px 0;text-align:center;color:var(--mix-t3,#5E6673);font-size:12px}
.mtabs{position:fixed;left:0;right:0;bottom:0;height:calc(58px + env(safe-area-inset-bottom));
  padding-bottom:env(safe-area-inset-bottom);background:var(--mix-panel,#12151A);
  border-top:1px solid var(--mix-border,#2B3139);display:flex;z-index:10}
.mt{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
  font-size:10px;color:var(--mix-t3,#5E6673);position:relative}
.mt span{font-size:16px}
.mt.on{color:#F0B90B}
.pd{position:absolute;top:6px;right:calc(50% - 20px);background:#F6465D;color:#fff;font-size:9px;
  border-radius:8px;padding:0 5px;font-style:normal}
.mgate{min-height:100vh;background:#0B0E11;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:10px;padding:24px}
.mgate b{color:#EAECEF;font-size:18px}
.mgate input{width:min(320px,80vw);height:42px;background:#181B21;border:1px solid #2B3139;border-radius:8px;
  color:#EAECEF;padding:0 12px;font-size:14px}
</style>
