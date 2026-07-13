<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)"
             :title="`单一规则 · ${symbol}`" width="560" class="symrulemodal">
    <div v-loading="loading">
      <div class="hint">该币的单独覆盖（coin SymbolRule 权威）；留空=回落全局/批量基线（灰字为基线值）。</div>
      <div class="sgrid">
        <div v-for="f in fields" :key="f.key" class="scol">
          <label>{{ f.label }}</label>
          <input v-model="f.value" class="inp" :placeholder="f.baseline != null ? String(f.baseline) : '继承'" />
          <i v-if="f.baseline != null" class="base">基线 {{ f.baseline }}</i>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button type="warning" :loading="saving" @click="save">保存单一规则（30s 热生效）</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

const props = defineProps({ modelValue: Boolean, symbol: String, code: { type: String, default: 'S3' } })
defineEmits(['update:modelValue'])
const fields = ref([]); const loading = ref(false); const saving = ref(false)

async function load() {
  if (!props.symbol) return
  loading.value = true
  try {
    const r = await mixApi.symbolRule(props.symbol, props.code)
    fields.value = (r.fields || []).map(f => ({ ...f, value: f.value == null ? '' : String(f.value) }))
  } catch (e) { ElMessage.error(e?.detail || e?.error || '读取失败（仅 S3 支持单一规则）'); fields.value = [] }
  finally { loading.value = false }
}
watch(() => props.modelValue, v => { if (v) load() })

async function save() {
  saving.value = true
  try {
    const out = fields.value.filter(f => f.value !== '').map(f => ({ key: f.key, value: f.value }))
    const r = await mixApi.symbolRuleSave(props.symbol, { fields: out })
    ElMessage.success(`已保存 ${r.applied?.length || 0} 项 · ${r.hotReloadSec}s 热生效`)
    load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
</script>

<style scoped lang="scss">
.hint { font-size: 11px; color: var(--el-text-color-secondary); margin-bottom: 12px; }
.sgrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.scol { display: flex; flex-direction: column; gap: 4px;
  label { font-size: 11px; color: var(--el-text-color-secondary); }
  .base { font-style: normal; font-size: 9.5px; color: var(--el-text-color-placeholder); } }
.inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 6px; color: #EAECEF; font-size: 12px; padding: 5px 8px; text-align: right;
  &:focus { outline: none; border-color: #F0B90B; } }
</style>
