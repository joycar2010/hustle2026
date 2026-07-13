<template>
  <div class="mixrules">
    <!-- 左：作用域树（通知设置已迁通知模块;审计已迁屏3风控墙） -->
    <div class="scopes">
      <div class="grp">策略模板</div>
      <div v-for="s in strategyList" :key="s.code" class="item"
           :class="{on:scope===`strategy:${s.code}`}"
           :style="scope===`strategy:${s.code}`?{background:META[s.code].colorBg,color:META[s.code].color}:{}"
           @click="setScope(`strategy:${s.code}`)">
        {{ s.code }} · {{ s.name }}
      </div>
      <div class="note">保存=差分写(只发变更键)·热生效引擎回读校验；变更审计移驻 屏3·风控墙</div>
    </div>

    <!-- 中：设定台（S3=共享面板,与中控台通用规则弹层同源;S2=人性化开关） -->
    <div class="stage">
      <div class="crumb">
        <b>{{ scopeLabel }}</b>
        <el-tag v-if="scope==='strategy:S3'" size="small" type="warning" effect="plain">coin 权威 · 30s 热重载</el-tag>
        <el-tag v-else-if="scope==='strategy:S2'" size="small" type="warning" effect="plain">gateway 权威 · 3s 热生效</el-tag>
        <span class="ver" v-if="scope!=='strategy:S3' && version">v{{ version }}</span>
      </div>

      <!-- S3：S3RulePanel 共享组件（40 字段五分组 + 自动划转 + 账户资金参数表,与中控台弹层同一实现） -->
      <div v-if="scope==='strategy:S3'">
        <S3RulePanel ref="s3p" />
        <div class="acts">
          <el-button type="warning" :loading="!!s3p?.saving" @click="s3p?.save()">保存设置（差分热生效）</el-button>
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
      </div>

      <!-- 其余作用域：引擎侧尚无权威读写点,如实标注 -->
      <div v-else class="empty">
        该作用域（{{ scopeLabel }}）引擎侧尚无权威配置读写点——不渲染假模板（防「UI 写了引擎不读」病）。
        S1 期现引擎参数随 armed 专场接入。
      </div>
    </div>
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
const fields = ref([])
const loading = ref(false)
const saving = ref(false)
const s3p = ref(null)
const s2 = ref({ mode: '', arm_mode: '', arm_symbols: '', max_notional_hard: '', max_portfolio_notional: '' })

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
    }
  } finally { loading.value = false }
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
onMounted(load)
</script>

<style scoped lang="scss">
.mixrules { display: grid; grid-template-columns: 200px 1fr; gap: 12px; align-items: start; }
.scopes { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 8px; display: flex; flex-direction: column; gap: 2px;
  .grp { font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px 2px; font-weight: 700; }
  .item { padding: 7px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; color: var(--el-text-color-regular);
    &:hover { background: var(--el-fill-color-light); }
    &.on { background: rgba(240,185,11,.14); color: #B8860B; font-weight: 700; } }
  .note { margin-top: 8px; font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px; border-top: 1px dashed var(--el-border-color); } }

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
</style>
