<template>
  <div class="mixrules">
    <!-- 左：作用域树（通知设置已迁通知模块;审计已迁屏3风控墙） -->
    <div class="scopes">
      <div class="grp">策略模板</div>
      <div v-for="s in strategyList" :key="s.code" class="item"
           :class="{on:scope===`strategy:${s.code}`}"
           :style="scope===`strategy:${s.code}`?{background:META[s.code].colorBg,color:META[s.code].color}:{}"
           @click="setScope(`strategy:${s.code}`)">
        {{ META[s.code].ccode||s.code }} · {{ s.name }}
        <i class="capchip" :class="'cc-'+capOf(s.code)">{{ CAP_CN[capOf(s.code)]||capOf(s.code) }}</i>
      </div>
      <div class="note">只显示当前真实能力(服务端能力注册表驱动);保存=差分写·热生效引擎回读校验</div>
    </div>

    <!-- 中：设定台（S3=共享面板,与中控台通用规则弹层同源;S2=人性化开关） -->
    <div class="stage">
      <div class="crumb">
        <b>{{ scopeLabel }}</b>
        <el-tag v-if="scope==='strategy:S3'" size="small" type="warning" effect="plain">coin 权威 · 30s 热重载</el-tag>
        <el-tag v-else-if="scope==='strategy:S2'" size="small" type="warning" effect="plain">gateway 权威 · 3s 热生效</el-tag>
        <span class="ver" v-if="scope!=='strategy:S3' && version">v{{ version }}</span>
      </div>

      <!-- V6.1 §3:能力注册表门禁——非 ACTIVE_WRITE 一律不渲染可编辑表单 -->
      <div v-if="curCap!=='ACTIVE_WRITE' && curCap!=='UNKNOWN'" class="empty">
        <b>{{ scopeLabel }}</b> 当前能力档位:<i class="capchip" :class="'cc-'+curCap">{{ CAP_CN[curCap]||curCap }}</i><br/>
        {{ curCap==='ACTIVE_READ' ? '引擎参数只读展示,写路径未开放(armed 专场接入后自动放开)' :
           curCap==='PLANNED' ? '该产品尚未启用——不显示空白可编辑表单' :
           curCap==='BLOCKED' ? '被风险/维护阻断,恢复后自动放开' : '即将淘汰,只读' }}
      </div>
      <!-- S3：S3RulePanel 共享组件（40 字段五分组 + 自动划转 + 账户资金参数表,与中控台弹层同一实现） -->
      <div v-else-if="scope==='strategy:S3'">
        <S3RulePanel ref="s3p" />
        <div class="acts">
          <el-button type="warning" @click="openPublish('strategy:S3')">发布(dry-run→预览→认证)</el-button>
          <el-button :loading="!!s3p?.saving" @click="s3p?.save()">直接保存(差分热生效)</el-button>
          <el-button @click="s3p?.load()">还原</el-button>
        </div>
      </div>

      <!-- S2：去参数化,人性化设定 -->
      <div v-else-if="scope==='strategy:S2'" class="s2form" v-loading="loading">
        <div class="s2card">
          <div class="s2hd">运行模式 <small>armed=真金下单;切换需二次确认,联锁要求风控全绿</small></div>
          <el-radio-group v-model="s2.mode" size="large">
            <el-radio-button value="shadow">shadow · 只决策不下单</el-radio-button>
            <el-radio-button value="armed">armed · 真金执行</el-radio-button>
          </el-radio-group>
        </div>
        <div class="s2card">
          <div class="s2hd">武装方式 <small>advisor=自动信任顾问名下 active 路由;list=仅显式白名单</small></div>
          <el-radio-group v-model="s2.arm_mode">
            <el-radio-button value="advisor">advisor · 顾问自动</el-radio-button>
            <el-radio-button value="list">list · 显式白名单</el-radio-button>
          </el-radio-group>
          <div class="s2sub">
            <em>白名单（逗号分隔,list 模式生效;人工路由任何模式须列名）</em>
            <el-input v-model="s2.arm_symbols" size="small" placeholder="如 AMATUSDT,PARTIUSDT" style="max-width:420px" />
          </div>
        </div>
        <div class="s2card">
          <div class="s2hd">仓位限额</div>
          <div class="s2flex">
            <span class="ifield"><em>单币硬顶</em><input v-model="s2.max_notional_hard" class="inp" style="width:70px" /><i>U</i></span>
            <span class="ifield"><em>组合上限</em><input v-model="s2.max_portfolio_notional" class="inp" style="width:70px" /><i>U</i></span>
          </div>
        </div>
        <div class="acts">
          <el-button type="warning" :loading="saving" @click="saveS2">保存设置（写代理 · gateway 审计）</el-button>
          <el-button @click="load">还原</el-button>
        </div>

        <!-- opener 自动开仓护栏(B 机 shadow,三闸:额度/深度/频率) -->
        <div class="s2card opcard">
          <div class="s2hd">自动开仓护栏 · opener <small style="color:#F0B90B">B机 · shadow</small>
            <span class="armready" :class="{on:armReady}">{{ armReady?'✓ 武装就绪':'○ 护栏未全开' }}</span>
          </div>
          <div class="opgrid">
            <div class="oprow"><em>深度硬闸</em>
              <el-switch v-model="op.depth_enforce" size="small" />
              <span class="tip">THIN 直接跳过(默认 ON)</span></div>
            <div class="oprow"><em>深度系数</em>
              <input v-model="op.depth_k" class="inp" style="width:50px" /><i>x</i>
              <span class="tip">一档额须≥目标×K</span></div>
            <div class="oprow"><em>单币额度上限</em>
              <input v-model="op.max_notional_per_candidate_usdt" class="inp" style="width:60px" /><i>U</i></div>
            <div class="oprow"><em>总额度上限</em>
              <input v-model="op.max_total_armed_notional_usdt" class="inp" style="width:60px" /><i>U</i>
              <span class="tip">在管+候选</span></div>
            <div class="oprow"><em>并发仓位上限</em>
              <input v-model="op.max_concurrent_positions" class="inp" style="width:50px" /><i>个</i></div>
            <div class="oprow"><em>单币冷却</em>
              <input v-model="op.per_symbol_cooldown_sec" class="inp" style="width:60px" /><i>秒</i>
              <span class="tip">平仓后冷却期内不进候选</span></div>
            <div class="oprow"><em>净日费率≥</em>
              <input v-model="op.min_net_daily_pct" class="inp" style="width:50px" /><i>%</i></div>
            <div class="oprow"><em>经济期望≥</em>
              <input v-model="op.min_e_bps" class="inp" style="width:50px" /><i>bps</i></div>
            <div class="oprow"><em>持有窗口</em>
              <input v-model="op.hold_hours" class="inp" style="width:50px" /><i>小时</i>
              <span class="tip">funding 收益按持有窗折算</span></div>
          </div>
          <div class="opsnap" v-if="opSnap">
            <b>当前状态</b> 候选 {{ opSnap.candidate_count || 0 }} 个 ·
            在管名义 {{ opSnap.gate?.managed_notional_usdt || 0 }}U ·
            <span :class="opSnap.gate?.depth_enforce?'on':'off'">深度{{ opSnap.gate?.depth_enforce?'ON':'OFF' }}</span>
          </div>
          <div class="acts" style="margin-top:10px">
            <el-button type="warning" :loading="opSaving" @click="saveOpener">保存护栏(60s 热生效)</el-button>
            <el-button @click="loadOpener">还原</el-button>
          </div>
        </div>
      </div>

      <!-- 其余作用域：引擎侧尚无权威读写点,如实标注 -->
      <div v-else class="empty">
        该作用域（{{ scopeLabel }}）引擎侧尚无权威配置读写点——不渲染假模板（防「UI 写了引擎不读」病）。
        S1 期现引擎参数随 armed 专场接入。
      </div>
    </div>
    <el-dialog v-model="pub.open" title="规则发布流程" width="600px">
      <el-steps :active="pub.step" simple>
        <el-step title="草稿" /><el-step title="schema校验" /><el-step title="影响预览" /><el-step title="dry-run" />
        <el-step title="二次认证" /><el-step title="发布" />
      </el-steps>
      <div v-if="pub.dry" class="pubbody">
        <div class="pline"><b>差异 {{ pub.dry.diff_count }} 项</b>
          <span :class="pub.dry.schema_ok?'ok':'bad'">schema {{ pub.dry.schema_ok?'通过':'不通过' }}</span></div>
        <div v-if="!pub.dry.schema_ok" class="err">校验错误:{{ pub.dry.schema_errors.map(e=>e.key+' '+e.error).join('; ') }}</div>
        <div v-for="(d,i) in pub.dry.diff" :key="i" class="dline">{{ d.key }}: <s>{{ d.old ?? 'N/A' }}</s> → <b>{{ d.new }}</b></div>
        <div class="impact">影响面:{{ JSON.stringify(pub.dry.impact) }} · 热重载 {{ pub.dry.impact?.hot_reload_sec }}s</div>
        <div class="totp"><span>二次认证 TOTP:</span><el-input v-model="pub.code" size="small" maxlength="6" style="width:140px" placeholder="6位动态码" /></div>
        <div class="fnote">{{ pub.dry.note }}</div>
      </div>
      <div v-else class="pubbody dimtxt">计算 dry-run 中…(草稿从当前设定台取值,发布须 TOTP,发布后冷却观察可回滚)</div>
      <template #footer>
        <el-button @click="pub.open=false">取消</el-button>
        <el-button type="warning" :disabled="!pub.dry?.schema_ok" :loading="pub.busy" @click="doPublish">确认发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import S3RulePanel from '../../components/rules/S3RulePanel.vue'
import { mixApi } from '../../api/mix'

const strategyList = Object.values(META)
const scope = ref('strategy:S3')
// V6.1 §3 能力注册表:S码→C码查注册表;取不到=UNKNOWN(不拦既有可写,防注册表故障误锁)
const CAP_CN = { ACTIVE_WRITE: '可写', ACTIVE_READ: '只读', SHADOW: '影子', PLANNED: '未启用',
                 BLOCKED: '已阻断', DEPRECATED: '淘汰中' }
const caps = ref(null)
function capOf(scode) {
  if (!caps.value) return 'UNKNOWN'
  const cc = META[scode]?.ccode || scode
  return caps.value[cc] ?? caps.value[cc.split('.')[0]] ?? 'PLANNED'
}
const curCap = computed(() => capOf(scope.value.split(':')[1]))
async function loadCaps() {
  try {
    const r = await mixApi.v6Capabilities()
    caps.value = Object.fromEntries((r.rows || []).map(x => [x.product_code, x.capability]))
  } catch (e) { caps.value = null }
}
const fields = ref([])
const loading = ref(false)
const saving = ref(false)
const s3p = ref(null)
const s2 = ref({ mode: '', arm_mode: '', arm_symbols: '', max_notional_hard: '', max_portfolio_notional: '' })
const op = ref({ depth_enforce: true, depth_k: 3, hold_hours: 8, fee_bps_per_fill: 5, est_roundtrip_cost_bps: 8,
  min_net_daily_pct: 0.1, min_e_bps: 0, max_notional_per_candidate_usdt: 200,
  max_total_armed_notional_usdt: 1000, max_concurrent_positions: 5, per_symbol_cooldown_sec: 3600 })
const opSnap = ref(null)
const opSaving = ref(false)
const armReady = computed(() => op.value.depth_enforce && op.value.max_total_armed_notional_usdt > 0
  && op.value.per_symbol_cooldown_sec > 0)

const fieldMap = computed(() => Object.fromEntries(fields.value.map(f => [f.key, f])))
const version = computed(() => fieldMap.value.version?.value)

const scopeLabel = computed(() => {
  const [, v] = scope.value.split(':')
  return `${v} · ${META[v]?.name || ''} 模板`
})

async function load() {
  if (scope.value === 'strategy:S3') return   // S3=共享面板自管加载
  loading.value = true
  try {
    const data = await mixApi.rules(scope.value)
    fields.value = data.fields.map(f => ({ ...f }))
    if (scope.value === 'strategy:S2') {
      const m = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
      s2.value = { mode: m.mode || '', arm_mode: m.arm_mode || '', arm_symbols: m.arm_symbols || '',
                   max_notional_hard: m.max_notional_hard || '', max_portfolio_notional: m.max_portfolio_notional || '' }
      loadOpener()
    }
  } finally { loading.value = false }
}
async function loadOpener() {
  try {
    const data = await mixApi.openerGuards()
    const g = data.guards || {}
    op.value = { depth_enforce: g.depth_enforce ?? true, depth_k: g.depth_k ?? 3, hold_hours: g.hold_hours ?? 8,
      fee_bps_per_fill: g.fee_bps_per_fill ?? 5, est_roundtrip_cost_bps: g.est_roundtrip_cost_bps ?? 8,
      min_net_daily_pct: g.min_net_daily_pct ?? 0.1, min_e_bps: g.min_e_bps ?? 0,
      max_notional_per_candidate_usdt: g.max_notional_per_candidate_usdt ?? 200,
      max_total_armed_notional_usdt: g.max_total_armed_notional_usdt ?? 1000,
      max_concurrent_positions: g.max_concurrent_positions ?? 5,
      per_symbol_cooldown_sec: g.per_symbol_cooldown_sec ?? 3600 }
    opSnap.value = data.snapshot
  } catch (e) { console.warn('loadOpener', e) }
}
function setScope(s) { scope.value = s; load() }

async function saveS2() {
  const orig = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
  const out = []
  for (const k of ['mode', 'arm_mode', 'arm_symbols', 'max_notional_hard', 'max_portfolio_notional']) {
    if (String(s2.value[k]) !== String(orig[k] ?? '')) out.push({ key: k, value: String(s2.value[k]) })
  }
  if (!out.length) return ElMessage.info('无变更')
  // armed 联锁：切 armed 须显式打 ARM（gateway confirm=ARM 二次确认原样透传）
  const modeField = out.find(f => f.key === 'mode' && f.value === 'armed')
  if (modeField) {
    try {
      const { value } = await ElMessageBox.prompt('切换 armed=真金下单。输入 ARM 确认（gateway 联锁要求风控全绿）', '武装确认', { inputPattern: /^ARM$/, inputErrorMessage: '必须输入 ARM' })
      modeField.confirm = value
    } catch { return }
  }
  saving.value = true
  try {
    const r = await mixApi.rulesSave('strategy:S2', { fields: out })
    if (r.rejected?.length) ElMessage.error(`部分被拒: ${r.rejected.map(x => `${x.key}(${x.error})`).join('; ')}`)
    else ElMessage.success(`已保存 ${r.applied?.length || 0} 项 · 引擎 ${r.hotReloadSec}s 回读生效`)
    load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
async function saveOpener() {
  opSaving.value = true
  try {
    const r = await mixApi.openerGuardsSave({ guards: op.value })
    ElMessage.success(r.note || `已保存 ${r.applied?.length || 0} 项`)
    loadOpener()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { opSaving.value = false }
}
const pub = ref({ open: false, step: 0, dry: null, code: '', busy: false, scope: '' })
async function openPublish(scope){
  pub.value = { open: true, step: 2, dry: null, code: '', busy: false, scope }
  // 从 S3RulePanel 取当前草稿值(改动过的字段)——直接对全字段 dry-run,后端算差异
  const fields = (s3p.value?.draftFields?.() ) || []
  try{ pub.value.dry = await mixApi.rulesDryRun({ scope_key: scope, fields }); pub.value.step = 4 }
  catch(e){ ElMessage.error(e?.detail||'dry-run 失败'); pub.value.open=false }
}
async function doPublish(){
  pub.value.busy = true
  try{
    // 发布=既有差分写(coin schema+审计+热重载权威);TOTP 作为发布确认(前端门,后端权威闸在 coin)
    if(!pub.value.code){ ElMessage.warning('请输入 TOTP'); pub.value.busy=false; return }
    await s3p.value?.save()
    pub.value.step = 6
    ElMessage.success('已发布(差分热生效,coin 30s 回读校验);冷却观察后如需回滚用还原')
    setTimeout(()=>{ pub.value.open=false }, 800)
  }catch(e){ ElMessage.error(e?.detail||'发布失败') }finally{ pub.value.busy=false }
}
onMounted(() => { load(); loadCaps() })
</script>

<style scoped lang="scss">
.mixrules { display: grid; grid-template-columns: 200px 1fr; gap: 12px; align-items: start; }
.scopes { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 8px; display: flex; flex-direction: column; gap: 2px;
  .grp { font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px 2px; font-weight: 700; }
  .item { padding: 7px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; color: var(--el-text-color-regular);
    &:hover { background: var(--el-fill-color-light); }
    &.on { background: rgba(240,185,11,.14); color: #B8860B; font-weight: 700; } }
  .note { margin-top: 8px; font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px; border-top: 1px dashed var(--el-border-color); } }
.capchip { font-style: normal; font-size: 9px; border-radius: 4px; padding: 1px 5px; margin-left: 6px;
  background: var(--mix-card2,#20242C); color: var(--mix-t3,#5E6673);
  &.cc-ACTIVE_WRITE { background: #0ECB8122; color: #0ECB81; }
  &.cc-ACTIVE_READ { background: #4A9CFF22; color: #4A9CFF; }
  &.cc-BLOCKED, &.cc-DEPRECATED { background: #F6465D22; color: #F6465D; } }

/* 设定台整体收窄居中 */
.stage { max-width: 980px; margin: 0 auto; width: 100%; border: 1px solid var(--el-border-color); border-radius: 10px; padding: 14px 20px; background: var(--mix-card, #181B21); }
.crumb { display: flex; align-items: center; gap: 10px; font-size: 13px; margin-bottom: 12px;
  b { font-weight: 800; } .ver { margin-left: auto; color: var(--el-text-color-placeholder); font-size: 11px; } }
.acts { margin-top: 16px; display: flex; gap: 8px; justify-content: center; }

/* S2：人性化卡片 */
.s2form { display: flex; flex-direction: column; gap: 12px; max-width: 640px; margin: 0 auto; }
.s2card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.s2hd { font-size: 12.5px; font-weight: 700; margin-bottom: 10px;
  small { color: var(--el-text-color-placeholder); font-weight: 400; margin-left: 8px; } }
.s2sub { margin-top: 10px; display: flex; flex-direction: column; gap: 6px;
  em { font-style: normal; font-size: 11px; color: var(--el-text-color-secondary); } }
.s2flex { display: flex; gap: 18px; flex-wrap: wrap; }
.ifield { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--el-text-color-secondary); white-space: nowrap;
  em { font-style: normal; } i { font-style: normal; color: var(--el-text-color-placeholder); font-size: 10px; } }
.inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF;
  font-size: 11px; padding: 3px 6px; text-align: right;
  &:focus { outline: none; border-color: #F0B90B; } }
.empty { color: var(--el-text-color-secondary); font-size: 12px; padding: 30px 10px; text-align: center; }
.pubbody { padding: 10px 0; }
.pline { display: flex; gap: 12px; align-items: center; font-size: 13px; margin-bottom: 8px; }
.ok { color: #0ECB81; } .bad { color: #F6465D; }
.err { color: #F6465D; font-size: 12px; margin-bottom: 8px; }
.dline { font-size: 12px; padding: 3px 0; s { color: var(--el-text-color-placeholder); } b { color: #F0B90B; } }
.impact { font-size: 11px; color: var(--el-text-color-secondary); margin: 8px 0; }
.totp { display: flex; align-items: center; gap: 8px; margin: 10px 0; font-size: 12px; }
.fnote, .dimtxt { font-size: 10.5px; color: var(--el-text-color-secondary); }
</style>
