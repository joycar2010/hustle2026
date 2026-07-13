<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)"
             :title="`单一规则 · ${baseOf}`" width="1080" top="6vh" class="symrulemodal">
    <div v-loading="loading">
      <!-- S3：coin SymbolRuleDialog 1:1 —— 批量行(SymbolRule 基线)+各子账户行(AccountSymbolRule 覆盖) -->
      <template v-if="code==='S3' && matrix">
        <div class="hint">顶行「批量」改某列 → 整列所有账户跟随；账户格<b class="amber">变色=单独覆盖</b>，<b>右键单格</b>或行尾「恢复整行」回到跟随批量；留空=跟随批量/全局(灰字为生效基线)。</div>
        <table class="mtx">
          <thead>
            <tr>
              <th class="tl">备注</th>
              <th>持币</th>
              <th v-for="c in matrix.cols" :key="c.key">{{ c.label }}</th>
              <th>移除/还币</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <!-- 批量行 -->
            <tr class="batchrow">
              <td class="tl gold">批量</td>
              <td class="dim">—</td>
              <td v-for="c in matrix.cols" :key="c.key">
                <select v-if="c.key==='follow_type'" v-model="common[c.key]" class="cell sel" @change="onBatchEdit(c.key)">
                  <option value="">跟随{{ phGlobal(c.key) ? `(${phGlobal(c.key)})` : '' }}</option>
                  <option value="market">market</option><option value="limit">limit</option>
                </select>
                <input v-else v-model="common[c.key]" class="cell" :placeholder="phGlobal(c.key)"
                       @input="onBatchEdit(c.key)" />
              </td>
              <td class="nowrap">
                <span class="pillbtn" :class="common.allow_remove===false ? 'neg':'pos'" @click="toggleAllow('allow_remove')">{{ common.allow_remove===false ? '禁移':'允移' }}</span>
                <span class="pillbtn" :class="common.allow_repay===false ? 'neg':'pos'" @click="toggleAllow('allow_repay')">{{ common.allow_repay===false ? '禁还':'允还' }}</span>
              </td>
              <td class="dim">基线</td>
            </tr>
            <!-- 子账户行 -->
            <tr v-for="a in matrix.accounts" :key="a.sub">
              <td class="tl">{{ a.note }} <i class="subid">#{{ a.sub }}</i></td>
              <td class="nowrap">
                <template v-if="heldTotal(a) > 0">
                  <span class="amber mono" :title="`本金${a.held.borrowed} 利息${a.held.interest}`">{{ a.held.borrowed.toFixed(4) }}</span>
                  <span class="pillbtn neg" @click="repayOne(a)">{{ repaying===a.sub ? '还币中':'还币' }}</span>
                </template>
                <span v-else class="dim">—</span>
              </td>
              <td v-for="c in matrix.cols" :key="c.key" :title="isMod(a,c.key) ? '右键恢复为批量值' : ''">
                <select v-if="c.key==='follow_type'" v-model="acct[a.sub][c.key]" class="cell sel"
                        :class="{mod:isMod(a,c.key)}" @change="markDirty(a.sub)"
                        @contextmenu.prevent="restoreCell(a.sub, c.key)">
                  <option value="">跟随{{ phCommon(c.key) ? `(${phCommon(c.key)})` : '' }}</option>
                  <option value="market">market</option><option value="limit">limit</option>
                </select>
                <input v-else v-model="acct[a.sub][c.key]" class="cell" :class="{mod:isMod(a,c.key)}"
                       :placeholder="phCommon(c.key)" @input="markDirty(a.sub)"
                       @contextmenu.prevent="restoreCell(a.sub, c.key)" />
              </td>
              <td class="dim">—</td>
              <td><span class="pillbtn" @click="restoreRow(a.sub)">恢复整行</span></td>
            </tr>
            <tr v-if="!matrix.accounts.length"><td :colspan="matrix.cols.length+4" class="dim" style="text-align:center;padding:16px">无子账户</td></tr>
          </tbody>
        </table>
      </template>

      <!-- 非 S3：只读引导（引擎全局参数,无单币覆盖） -->
      <template v-else-if="code!=='S3'">
        <div class="hint">{{ ro.note || `${code} 无单币规则` }}</div>
        <div class="rogrid">
          <div v-for="f in ro.fields || []" :key="f.key" class="rocol"><label>{{ f.label }}</label><b>{{ f.value ?? '—' }}</b></div>
        </div>
      </template>
    </div>
    <template #footer>
      <span class="ftnote" v-if="code==='S3'">保存后 coin 事件驱动 0 秒热重载生效</span>
      <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button v-if="code==='S3'" type="warning" :loading="saving" :disabled="!dirty.size" @click="save">保存({{ dirty.size }} 项改动)</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mixApi } from '../../api/mix'

const props = defineProps({ modelValue: Boolean, symbol: String, code: { type: String, default: 'S3' } })
const emit = defineEmits(['update:modelValue'])
const baseOf = computed(() => (props.symbol || '').replace('USDT', ''))

const matrix = ref(null)
const common = reactive({})
const acct = reactive({})
const dirty = ref(new Set())
const loading = ref(false); const saving = ref(false); const repaying = ref(null)
const ro = ref({})

const S = v => (v == null ? '' : String(v))
const phGlobal = k => S(matrix.value?.globalBaseline?.[k])
// 账户格基线 = 批量值 ?? 全局值
const phCommon = k => (common[k] !== '' && common[k] != null) ? S(common[k]) : phGlobal(k)
const heldTotal = a => (a.held?.borrowed || 0) + (a.held?.interest || 0)
const isMod = (a, k) => { const v = acct[a.sub]?.[k]; return v != null && v !== '' && S(v) !== phCommon(k) }

function markDirty(who) { const n = new Set(dirty.value); n.add(String(who)); dirty.value = n }
// 批量行改某列 = 清掉该列所有账户覆盖 → 整列跟随（coin 语义）
function onBatchEdit(key) {
  for (const a of matrix.value.accounts) {
    if (acct[a.sub][key] !== '' && acct[a.sub][key] != null) { acct[a.sub][key] = ''; markDirty(a.sub) }
  }
  markDirty('common')
}
function toggleAllow(k) { common[k] = common[k] === false; markDirty('common') }
function restoreCell(sub, key) { if (acct[sub][key] !== '') { acct[sub][key] = ''; markDirty(sub) } }
function restoreRow(sub) { for (const c of matrix.value.cols) acct[sub][c.key] = ''; markDirty(sub) }

async function repayOne(a) {
  const total = heldTotal(a)
  try {
    await ElMessageBox.confirm(
      `确认为 ${a.note} 还清 ${baseOf.value}？\n本金 ${a.held.borrowed} + 利息 ${a.held.interest} ≈ ${total.toFixed(6)}\n还清后立即恢复自动借币（挂单差为负会秒级重借）。`,
      '还币', { type: 'warning', confirmButtonText: '还币' })
  } catch { return }
  repaying.value = a.sub
  try {
    await mixApi.coinMenu(props.symbol, { action: 'partial_repay', sub: a.sub, amount: total })
    ElMessage.success(`${a.note} 还币已提交（coin 权威执行）`)
  } catch (e) { ElMessage.error(e?.detail || e?.error || '还币失败') }
  repaying.value = null
}

async function load() {
  if (!props.symbol) return
  loading.value = true
  dirty.value = new Set()
  try {
    if (props.code === 'S3') {
      const m = await mixApi.symbolRuleMatrix(props.symbol)
      matrix.value = m
      for (const c of m.cols) common[c.key] = S(m.common?.[c.key])
      common.allow_remove = m.common?.allow_remove
      common.allow_repay = m.common?.allow_repay
      for (const a of m.accounts) {
        acct[a.sub] = {}
        for (const c of m.cols) acct[a.sub][c.key] = S(a.rules?.[c.key])
      }
    } else {
      ro.value = await mixApi.symbolRule(props.symbol, props.code)
    }
  } catch (e) { ElMessage.error(e?.detail || e?.error || '读取失败'); matrix.value = null }
  finally { loading.value = false }
}
watch(() => props.modelValue, v => { if (v) load() })

async function save() {
  // 防呆(coin 课):开点差为负而生效平点差不是更低的负值 → 开完即平
  const num = v => (v === '' || v == null ? null : parseFloat(v))
  const gClose = num(phGlobal('close_spread'))
  const rowsToCheck = []
  if (dirty.value.has('common')) rowsToCheck.push({ o: num(common.open_spread), c: num(common.close_spread) ?? gClose })
  for (const a of matrix.value.accounts) {
    if (dirty.value.has(String(a.sub))) {
      rowsToCheck.push({ o: num(acct[a.sub].open_spread) ?? num(common.open_spread), c: num(acct[a.sub].close_spread) ?? num(common.close_spread) ?? gClose })
    }
  }
  if (rowsToCheck.some(r => r.o != null && r.o < 0 && (r.c == null || r.c >= 0))) {
    try {
      await ElMessageBox.confirm('开仓值为负,但生效的平仓值不是更低的负值:\n负点差行情下开仓后大概率立即满足平仓条件、开完即平。\n确认按当前值保存?', '防呆提醒', { type: 'warning' })
    } catch { return }
  }
  saving.value = true
  try {
    const body = { accounts: [] }
    if (dirty.value.has('common')) {
      body.common = {}
      for (const c of matrix.value.cols) body.common[c.key] = common[c.key]
      if (common.allow_remove !== undefined) body.common.allow_remove = common.allow_remove
      if (common.allow_repay !== undefined) body.common.allow_repay = common.allow_repay
    }
    for (const a of matrix.value.accounts) {
      if (dirty.value.has(String(a.sub))) {
        const fields = {}
        for (const c of matrix.value.cols) fields[c.key] = acct[a.sub][c.key]
        body.accounts.push({ sub: a.sub, fields })
      }
    }
    const r = await mixApi.symbolRuleMatrixSave(props.symbol, body)
    ElMessage.success(`已保存 ${r.applied?.length || 0} 项 · 0 秒热生效`)
    load()
  } catch (e) { ElMessage.error(e?.detail || e?.error || '保存失败') }
  finally { saving.value = false }
}
</script>

<style scoped lang="scss">
.hint { font-size: 11px; color: var(--el-text-color-secondary); margin-bottom: 10px; b { font-weight: 700; } .amber { color: #F0B90B; } }
.mtx { border-collapse: collapse; width: 100%; font-size: 11px;
  th { background: #0d0d14; color: var(--el-text-color-secondary); padding: 6px 4px; font-weight: 600; white-space: nowrap; border-bottom: 1px solid var(--el-border-color); text-align: center; }
  td { padding: 4px; text-align: center; border-bottom: 1px solid rgba(255,255,255,.05); white-space: nowrap; }
  .tl { text-align: left; padding-left: 8px; }
  .batchrow { background: rgba(240,185,11,.05); } }
.gold { color: #F0B90B; font-weight: 700; }
.amber { color: #f59e0b; }
.mono { font-family: monospace; }
.dim { color: var(--el-text-color-placeholder); }
.subid { font-style: normal; font-size: 9px; color: var(--el-text-color-placeholder); }
.nowrap { white-space: nowrap; }
.cell { width: 62px; background: #12151A; border: 1px solid var(--el-border-color); border-radius: 5px; color: #EAECEF; font-size: 11px; padding: 3px 5px; text-align: right;
  &:focus { outline: none; border-color: #F0B90B; }
  &.mod { color: #f59e0b; border-color: rgba(245,158,11,.55); background: rgba(245,158,11,.08); }
  &::placeholder { color: rgba(255,255,255,.22); } }
.sel { text-align: left; width: 78px; }
.pillbtn { display: inline-block; border: 1px solid var(--el-border-color); border-radius: 10px; padding: 1px 8px; font-size: 10px; cursor: pointer; user-select: none; margin: 0 2px; color: var(--el-text-color-secondary);
  &:hover { border-color: #F0B90B; color: #F0B90B; }
  &.pos { background: rgba(14,203,129,.12); color: #0ECB81; border-color: rgba(14,203,129,.3); }
  &.neg { background: rgba(246,70,93,.12); color: #F6465D; border-color: rgba(246,70,93,.3); } }
.rogrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.rocol { display: flex; flex-direction: column; gap: 3px; border: 1px solid var(--el-border-color); border-radius: 8px; padding: 8px 10px;
  label { font-size: 11px; color: var(--el-text-color-placeholder); } b { font-size: 13px; } }
.ftnote { margin-right: auto; font-size: 10.5px; color: var(--el-text-color-placeholder); }
</style>
