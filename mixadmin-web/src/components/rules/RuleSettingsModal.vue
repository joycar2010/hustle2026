<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)"
             :title="`规则设置 · ${code} ${nameOf}`" width="900" top="6vh" class="rulemodal">
    <div v-loading="loading">
      <!-- S3：coin 规则模态框 1:1（40 字段五分组,flex 折行居中） -->
      <div v-if="code==='S3'" class="s3form">
        <template v-for="grp in S3_GROUPS" :key="grp.title">
          <div class="ghd">{{ grp.title }}</div>
          <div class="gflex">
            <template v-for="k in grp.keys" :key="k">
              <label v-if="fieldMap[k] && S3_META[k].type==='bool'" class="pill" :class="{on: isTrue(fieldMap[k].value)}"
                     :title="S3_META[k].tip" @click="toggleBool(k)">{{ S3_META[k].label }}</label>
              <span v-else-if="fieldMap[k] && S3_META[k].type==='select'" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <select v-model="fieldMap[k].value" class="sel">
                  <option v-for="o in S3_META[k].options" :key="o" :value="o">{{ o }}</option>
                </select>
              </span>
              <span v-else-if="fieldMap[k]" class="ifield" :title="S3_META[k].tip">
                <em>{{ S3_META[k].label }}</em>
                <input v-model="fieldMap[k].value" class="inp" :style="{width:(S3_META[k].w||64)+'px'}" />
                <i v-if="S3_META[k].suffix">{{ S3_META[k].suffix }}</i>
              </span>
            </template>
          </div>
        </template>
      </div>

      <!-- S2：人性化设定 -->
      <div v-else-if="code==='S2'" class="s2form">
        <div class="s2card">
          <div class="s2hd">运行模式 <small>armed=真金下单；切换需输 ARM 二次确认（风控联锁）</small></div>
          <el-radio-group v-model="s2.mode"><el-radio-button value="shadow">影子</el-radio-button><el-radio-button value="armed">武装</el-radio-button></el-radio-group>
        </div>
        <div class="s2card">
          <div class="s2hd">武装方式 <small>advisor=自动信任顾问路由；list=显式白名单</small></div>
          <el-radio-group v-model="s2.arm_mode"><el-radio-button value="advisor">顾问自动</el-radio-button><el-radio-button value="list">显式白名单</el-radio-button></el-radio-group>
          <div class="s2sub"><em>白名单（逗号分隔）</em><el-input v-model="s2.arm_symbols" size="small" style="max-width:420px" /></div>
        </div>
        <div class="s2card">
          <div class="s2hd">仓位限额</div>
          <div class="s2flex">
            <span class="ifield"><em>单币硬顶</em><input v-model="s2.max_notional_hard" class="inp" style="width:70px" /><i>U</i></span>
            <span class="ifield"><em>组合上限</em><input v-model="s2.max_portfolio_notional" class="inp" style="width:70px" /><i>U</i></span>
          </div>
        </div>
      </div>

      <!-- S1/S4：引擎 env 控制,展示当前生效参数(只读) -->
      <div v-else-if="fields.length" class="roform">
        <div class="ronote">{{ code }} 策略参数由引擎 env 控制（不支持网页热改）；以下为当前生效值：</div>
        <div class="rogrid">
          <div v-for="f in fields" :key="f.key" class="rocol"><label>{{ f.label }}</label><b>{{ f.value }}</b></div>
        </div>
      </div>
      <div v-else class="empty">{{ code }} 策略未建 / 无可展示参数。</div>
    </div>
    <template #footer>
      <span class="ver" v-if="version">当前 v{{ version }}</span>
      <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button v-if="code==='S3' || code==='S2'" type="warning" :loading="saving" @click="save">保存设置（热生效）</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'
import { S3_META, S3_GROUPS } from './s3meta'

const props = defineProps({ modelValue: Boolean, code: String })
defineEmits(['update:modelValue'])
const NAMES = { S1: '单所期现基差', S2: '双合约期期', S3: '借币反向/点差', S4: '借贷利率', S5: '事件/LST', S6: '费率飞轮' }
const nameOf = computed(() => NAMES[props.code] || '')
const scopeOf = c => ({ S1: 'strategy:S1', S2: 'strategy:S2', S3: 'strategy:S3', S4: 'strategy:S4' }[c])

const fields = ref([]); const loading = ref(false); const saving = ref(false)
const s2 = ref({ mode: '', arm_mode: '', arm_symbols: '', max_notional_hard: '', max_portfolio_notional: '' })
const fieldMap = computed(() => Object.fromEntries(fields.value.map(f => [f.key, f])))
const version = computed(() => fieldMap.value.version?.value)
const isTrue = v => String(v) === 'True' || String(v) === 'true'
function toggleBool(k) { fieldMap.value[k].value = isTrue(fieldMap.value[k].value) ? 'False' : 'True' }

async function load() {
  const scope = scopeOf(props.code)
  if (!scope) { fields.value = []; return }
  loading.value = true
  try {
    const data = await mixApi.rules(scope)
    fields.value = data.fields.map(f => ({ ...f }))
    if (props.code === 'S2') {
      const m = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
      s2.value = { mode: m.mode || '', arm_mode: m.arm_mode || '', arm_symbols: m.arm_symbols || '', max_notional_hard: m.max_notional_hard || '', max_portfolio_notional: m.max_portfolio_notional || '' }
    }
  } finally { loading.value = false }
}
watch(() => props.modelValue, v => { if (v) load() })

async function save() {
  saving.value = true
  try {
    if (props.code === 'S3') {
      const r = await mixApi.rulesSave('strategy:S3', { fields: fields.value })
      if (r.saved) ElMessage.success(`已保存 ${r.applied?.length || 0} 项 · ${r.hotReloadSec}s 热生效`)
      else ElMessage.info(r.note || '无变更')
    } else if (props.code === 'S2') {
      const orig = Object.fromEntries(fields.value.map(f => [f.key, f.value]))
      const out = []
      for (const k of ['mode', 'arm_mode', 'arm_symbols', 'max_notional_hard', 'max_portfolio_notional']) {
        if (String(s2.value[k]) !== String(orig[k] ?? '')) out.push({ key: k, value: String(s2.value[k]) })
      }
      if (!out.length) { ElMessage.info('无变更'); return }
      const armField = out.find(f => f.key === 'mode' && f.value === 'armed')
      if (armField) {
        const { value } = await ElMessageBox.prompt('切武装=真金下单，输入 ARM 确认', '武装确认', { inputPattern: /^ARM$/, inputErrorMessage: '必须输入 ARM' })
        armField.confirm = value
      }
      const r = await mixApi.rulesSave('strategy:S2', { fields: out })
      if (r.rejected?.length) ElMessage.error('部分被拒: ' + r.rejected.map(x => `${x.key}`).join(','))
      else ElMessage.success(`已保存 ${r.applied?.length || 0} 项`)
    }
    load()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
</script>

<style scoped lang="scss">
.s3form { display: flex; flex-direction: column; gap: 6px; max-height: 66vh; overflow-y: auto; }
.ghd { font-size: 11px; font-weight: 800; color: #F0B90B; letter-spacing: 1px; margin-top: 8px; padding-bottom: 4px; border-bottom: 1px dashed rgba(240,185,11,.25); }
.gflex { display: flex; flex-wrap: wrap; gap: 8px 14px; justify-content: center; padding: 8px 0 4px; }
.ifield { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--el-text-color-secondary); white-space: nowrap;
  em { font-style: normal; } i { font-style: normal; color: var(--el-text-color-placeholder); font-size: 10px; } }
.inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11px; padding: 3px 6px; text-align: right;
  &:focus { outline: none; border-color: #F0B90B; } }
.sel { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11px; padding: 3px 4px; &:focus { outline: none; border-color: #F0B90B; } }
.pill { display: inline-flex; align-items: center; border: 1px solid var(--el-border-color); border-radius: 20px; padding: 3px 12px; font-size: 11px; color: var(--el-text-color-secondary); cursor: pointer; user-select: none;
  &.on { background: rgba(240,185,11,.16); border-color: #F0B90B; color: #F0B90B; font-weight: 700; } }
.s2form { display: flex; flex-direction: column; gap: 12px; max-width: 640px; margin: 0 auto; }
.s2card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.s2hd { font-size: 12.5px; font-weight: 700; margin-bottom: 10px; small { color: var(--el-text-color-placeholder); font-weight: 400; margin-left: 8px; } }
.s2sub { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; em { font-style: normal; font-size: 11px; color: var(--el-text-color-secondary); } }
.s2flex { display: flex; gap: 18px; flex-wrap: wrap; }
.roform { padding: 4px; }
.ronote { font-size: 11.5px; color: var(--el-text-color-secondary); margin-bottom: 12px; }
.rogrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.rocol { display: flex; flex-direction: column; gap: 3px; border: 1px solid var(--el-border-color); border-radius: 8px; padding: 8px 10px;
  label { font-size: 11px; color: var(--el-text-color-placeholder); } b { font-size: 13px; color: var(--el-text-color-primary); } }
.empty { color: var(--el-text-color-secondary); font-size: 12px; padding: 30px; text-align: center; }
.ver { margin-right: auto; font-size: 11px; color: var(--el-text-color-placeholder); }
</style>
