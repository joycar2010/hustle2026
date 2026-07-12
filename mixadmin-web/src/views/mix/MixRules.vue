<template>
  <div class="mixrules">
    <!-- 左：五级作用域树 -->
    <div class="scopes">
      <div class="grp">总闸</div>
      <div class="item" :class="{on:scope==='global'}" @click="setScope('global')">全局总闸</div>
      <div class="item dim" @click="ElMessage.info('通知设置：渠道/模板/间隔/次数/令牌桶（M4 接线）')">通知设置</div>
      <div class="grp">策略模板</div>
      <div v-for="s in strategyList" :key="s.code" class="item"
           :class="{on:scope===`strategy:${s.code}`}"
           :style="scope===`strategy:${s.code}`?{background:META[s.code].colorBg,color:META[s.code].color}:{}"
           @click="setScope(`strategy:${s.code}`)">
        {{ s.code }} · {{ s.name }}
      </div>
      <div class="grp">覆盖层</div>
      <div class="item" :class="{on:scope==='venue:binance'}" @click="setScope('venue:binance')">venue · 币安</div>
      <div class="item" :class="{on:scope==='symbol:BNBUSDT'}" @click="setScope('symbol:BNBUSDT')">币种 · BNBUSDT</div>
      <div class="item" :class="{on:scope==='account:hustle-001'}" @click="setScope('account:hustle-001')">账户 · hustle-001</div>
      <div class="note">五级作用域就近覆盖 · 每作用域唯一行 + 唯一索引 · 保存热生效（3s 回读）</div>
    </div>

    <!-- 中：字段表单（继承字段灰显，点击覆盖变可编辑） -->
    <div class="form">
      <div class="crumb">
        <span>全局</span>
        <template v-if="scope!=='global'"><i>›</i><b>{{ scopeLabel }}</b></template>
        <el-tag v-if="data?.uniqueRow" size="small" type="success" effect="plain">唯一行</el-tag>
      </div>
      <div class="fields" v-loading="loading">
        <div v-for="f in fields" :key="f.key" class="field" :class="{inh:f.inherited, locked:f.locked}">
          <label>{{ f.label }}
            <el-tag v-if="f.inherited" size="small" type="info" effect="plain" @click.stop="overrideField(f)">继承 · 点击覆盖</el-tag>
            <el-tag v-if="f.locked" size="small" type="danger" effect="plain">强制</el-tag>
          </label>
          <template v-if="f.type==='switch'">
            <el-switch v-model="f.value" active-value="on" inactive-value="off" :disabled="f.inherited||f.locked" />
          </template>
          <template v-else-if="f.type==='enum'">
            <el-radio-group v-model="f.value" size="small" :disabled="f.inherited">
              <el-radio-button v-for="o in f.options" :key="o" :value="o">{{ o }}</el-radio-button>
            </el-radio-group>
          </template>
          <template v-else>
            <el-input v-model="f.value" size="small" :disabled="f.inherited" style="max-width:220px">
              <template v-if="f.unit" #append>{{ f.unit }}</template>
            </el-input>
          </template>
        </div>
      </div>
      <div class="acts">
        <el-button type="warning" :loading="saving" @click="save">保存设置（热生效）</el-button>
        <el-button @click="load">还原</el-button>
      </div>
    </div>

    <!-- 右：变更审计 -->
    <div class="audit">
      <b>变更审计 · {{ scopeLabel }}</b>
      <div v-for="(a,i) in audit" :key="i" class="arec">
        <div class="l1"><span>{{ a.field }}</span><em>{{ a.at }}</em></div>
        <div class="l2"><span class="chg">{{ a.change }}</span><em>{{ a.user }}</em></div>
      </div>
      <div v-if="!audit.length" class="empty">暂无变更</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { STRATEGY_META as META } from '../../components/PositionTable/types'
import { mixApi } from '../../api/mix'

const strategyList = Object.values(META)
const scope = ref('strategy:S3')
const data = ref(null)
const fields = ref([])
const audit = ref([])
const loading = ref(false)
const saving = ref(false)

const scopeLabel = computed(() => {
  if (scope.value === 'global') return '全局总闸'
  const [k, v] = scope.value.split(':')
  if (k === 'strategy') return `${v} · ${META[v]?.name || ''} 模板`
  return { venue: 'venue · ', symbol: '币种 · ', account: '账户 · ' }[k] + v
})

async function load() {
  loading.value = true
  try {
    data.value = await mixApi.rules(scope.value)
    fields.value = data.value.fields.map(f => ({ ...f }))
    audit.value = await fetchAudit()
  } finally { loading.value = false }
}
async function fetchAudit() {
  try { return await mixApi.rulesAudit(scope.value) }
  catch { return [] }
}
function setScope(s) { scope.value = s; load() }
function overrideField(f) { f.inherited = false; ElMessage.info(`「${f.label}」已转为本作用域覆盖`) }
async function save() {
  saving.value = true
  try {
    const r = await mixApi.rulesSave(scope.value, { fields: fields.value })
    ElMessage.success(`已保存 · ${r.hotReloadSec}s 热生效（引擎回读）`)
    audit.value = await fetchAudit()
  } catch (e) { ElMessage.error(e?.error || '保存失败') }
  finally { saving.value = false }
}
onMounted(load)
</script>

<style scoped lang="scss">
.mixrules { display: grid; grid-template-columns: 200px 1fr 280px; gap: 12px; align-items: start; }
.scopes { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 8px; display: flex; flex-direction: column; gap: 2px;
  .grp { font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px 2px; font-weight: 700; }
  .item { padding: 6px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; color: var(--el-text-color-regular);
    &:hover { background: var(--el-fill-color-light); }
    &.on { background: rgba(240,185,11,.14); color: #B8860B; font-weight: 700; }
    &.dim { color: var(--el-text-color-secondary); } }
  .note { margin-top: 8px; font-size: 10px; color: var(--el-text-color-placeholder); padding: 6px 8px; border-top: 1px dashed var(--el-border-color); } }
.form { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 12px 16px;
  .crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 10px;
    i { color: var(--el-text-color-placeholder); font-style: normal; } b { font-weight: 800; } }
  .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px 20px; }
  .field { display: flex; flex-direction: column; gap: 5px;
    label { font-size: 11px; color: var(--el-text-color-secondary); display: flex; gap: 6px; align-items: center; }
    &.inh { opacity: .75; } }
  .acts { margin-top: 14px; display: flex; gap: 8px; } }
.audit { border: 1px solid var(--el-border-color); border-radius: 10px; padding: 12px; font-size: 12px; display: flex; flex-direction: column; gap: 8px;
  .arec { background: var(--el-fill-color-light); border-radius: 6px; padding: 6px 8px;
    .l1, .l2 { display: flex; justify-content: space-between; }
    .l1 span { font-weight: 700; } em { font-style: normal; color: var(--el-text-color-placeholder); font-size: 10px; }
    .chg { color: #B8860B; } }
  .empty { color: var(--el-text-color-placeholder); } }
</style>
