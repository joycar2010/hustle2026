<template>
  <!-- 部分还币[指定]——coin PartialRepayDialog 1:1 复刻:
       逐子账户 现币/借币/待还(本金+利息);每行 还币数量(币)/还币金额(U) 互斥自填,
       还币/一键全还/卖回残留;底部 暂停自动借币30分 + 全部账户一键全还。
       动作经 coinMenu partial_repay 代理(coin 状态机权威);数据=panel 60s 快照+成功后乐观递减。 -->
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)"
             width="780" top="6vh" class="repaymodal" :close-on-click-modal="!bulkBusy" :show-close="!bulkBusy">
    <template #header>
      <span class="rhd">部分还币[指定] — 币种: <b class="gold">{{ base }}</b>
        <em class="sub">自填数量单独还,或「一键全还」按本金+利息全额</em></span>
    </template>
    <div v-loading="loading">
      <table class="rtable">
        <thead>
          <tr>
            <th class="tl">账户</th>
            <th title="当前手上可用现币(panel 60s 快照)">现币</th>
            <th title="杠杆户借币本金">借币</th>
            <th title="本金+利息合计(待还)">借币金额</th>
            <th title="按币数量还;与「还币金额」二选一,填一个另一个自动清空">还币数量</th>
            <th title="按USDT金额还:coin 按现价换算成币数量;与「还币数量」二选一">还币金额(U)</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.sub">
            <td class="tl">{{ r.note }}</td>
            <td class="num">{{ r.free > 1e-8 ? r.free.toFixed(4) : 0 }}</td>
            <td class="num amber">{{ r.borrowed > 1e-8 ? r.borrowed.toFixed(4) : 0 }}</td>
            <td class="num">{{ hasDebt(r) ? r.total.toFixed(4) : 0 }}</td>
            <td class="ctr">
              <input v-model="qty[r.sub]" class="cinp" :placeholder="hasDebt(r) ? r.total.toFixed(2) : '0'"
                     :disabled="!hasDebt(r) || bulkBusy" @input="qty[r.sub] && (usdt[r.sub]='')" />
            </td>
            <td class="ctr">
              <input v-model="usdt[r.sub]" class="cinp" :placeholder="hasDebt(r) ? 'USDT' : '0'"
                     :disabled="!hasDebt(r) || bulkBusy" @input="usdt[r.sub] && (qty[r.sub]='')" />
            </td>
            <td class="ctr ops">
              <button class="pbtn gold" :disabled="!hasDebt(r) || busy===r.sub || bulkBusy"
                      :title="hasDebt(r) ? undefined : '无借币,无需还币;现币残留用「卖回」清理'"
                      @click="submitRow(r)">{{ busy===r.sub ? '还币中' : '还币' }}</button>
              <button class="pbtn amberb" :disabled="!hasDebt(r) || busy===r.sub || bulkBusy"
                      @click="doRepay(r, { qty: r.total })">一键全还</button>
              <button v-if="!hasDebt(r) && r.free > 1e-8" class="pbtn green" :disabled="busy===r.sub || bulkBusy"
                      title="无债务但杠杆户仍有现币残留(平仓超买/尾批零头),市价卖回 USDT"
                      @click="sellResidual(r)">{{ busy===r.sub ? '卖回中' : '卖回' }}</button>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" class="edim">无子账户（coin 面板快照为空）</td></tr>
        </tbody>
      </table>
      <div class="fage" v-if="age != null">面板快照 {{ age }}s 前 · 还币结果以 coin 状态机为准,数值随下轮快照对账</div>
    </div>
    <template #footer>
      <label class="pause" title="不勾:还完立即恢复自动借币(挂单差为负会秒级重借,持续囤券语义)。勾选:暂停30分钟">
        <input type="checkbox" v-model="pauseBorrow" class="ck" />还币后暂停该币自动借币 30 分钟
      </label>
      <el-button :disabled="bulkBusy" @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button type="warning" :loading="bulkBusy" @click="repayAllAccounts">全部账户一键全还</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { mixApi } from '../../api/mix'

const props = defineProps({ modelValue: Boolean, symbol: String })
const emit = defineEmits(['update:modelValue', 'done'])

const rows = ref([])
const age = ref(null)
const loading = ref(false)
const busy = ref(null)          // 单账户还币中(sub)
const bulkBusy = ref(false)
const pauseBorrow = ref(false)
const qty = reactive({})        // 各账户还币数量(币)
const usdt = reactive({})       // 各账户还币金额(USDT),与数量互斥
const base = computed(() => String(props.symbol || '').replace('USDT', ''))
const hasDebt = r => r.total > 1e-8

async function load() {
  loading.value = true
  try {
    const d = await mixApi.repayPanel(props.symbol)
    rows.value = d.rows || []
    age.value = d.panelAgeSec
  } catch (e) { rows.value = []; ElMessage.error(e?.detail || e?.error || '面板读取失败') }
  finally { loading.value = false }
}
watch(() => props.modelValue, v => { if (v) { Object.keys(qty).forEach(k => delete qty[k]); Object.keys(usdt).forEach(k => delete usdt[k]); load() } })

// qty=按币数量还;usdtAmt=按USDT金额还(coin 现价换算,超债自动封顶)。互斥由输入框保证只传其一。
async function doRepay(r, opts) {
  if ((opts.qty ?? 0) <= 0 && (opts.usdtAmt ?? 0) <= 0) return ElMessage.error('还币数量/金额需为正数')
  busy.value = r.sub
  try {
    const body = { action: 'partial_repay', sub: r.sub }
    if (opts.qty) body.amount = opts.qty
    if (opts.usdtAmt) body.amount_usdt = opts.usdtAmt
    if (pauseBorrow.value) body.pause_borrow = true
    await mixApi.coinMenu(props.symbol, body)
    // 乐观递减(coin 同款):按数量还直接减本金;按金额还等下轮快照对账
    if (opts.qty) {
      r.borrowed = Math.max(0, r.borrowed - opts.qty)
      r.total = Math.max(0, r.total - opts.qty)
    }
    ElMessage.success(`${r.note} ${base.value} 还币已提交（coin 状态机执行）`)
    qty[r.sub] = ''; usdt[r.sub] = ''
    emit('done')
  } catch (e) { ElMessage.error(`${r.note} 还币失败: ${e?.detail || e?.error || e}`) }
  finally { busy.value = null }
}

function submitRow(r) {
  const rawQty = String(qty[r.sub] ?? '').trim()
  const rawAmt = String(usdt[r.sub] ?? '').trim()
  if (rawQty !== '') {
    const v = parseFloat(rawQty)
    if (isNaN(v) || v <= 0) return ElMessage.error('还币数量需为正数')
    if (v > r.total + 1e-8) return ElMessage.error(`${r.note} 还币数量 ${v} 超过待还 ${r.total.toFixed(4)} ${base.value},请重新输入`)
    return doRepay(r, { qty: v })
  }
  if (rawAmt !== '') {
    const v = parseFloat(rawAmt)
    if (isNaN(v) || v <= 0) return ElMessage.error('还币金额需为正数')
    return doRepay(r, { usdtAmt: v })
  }
  doRepay(r, { qty: r.total })   // 两框都留空=全额还
}

// 卖回现币残留(零债务行):平仓超买/尾批零头,走 partial_repay 的 sell_residual 分支市价卖回
async function sellResidual(r) {
  busy.value = r.sub
  try {
    await mixApi.coinMenu(props.symbol, { action: 'partial_repay', sub: r.sub, amount: r.free, sell_residual: true })
    ElMessage.success(`${r.note} 卖回已提交`)
    emit('done')
  } catch (e) { ElMessage.error(`${r.note} 卖回失败: ${e?.detail || e?.error || e}`) }
  finally { busy.value = null }
}

// 全部账户一键全还:逐账户全额(本金+利息)
async function repayAllAccounts() {
  const need = rows.value.filter(hasDebt)
  if (!need.length) return ElMessage.info('当前无借币可还')
  bulkBusy.value = true
  for (const r of need) {
    busy.value = r.sub
    try {
      const body = { action: 'partial_repay', sub: r.sub, amount: r.total }
      if (pauseBorrow.value) body.pause_borrow = true
      await mixApi.coinMenu(props.symbol, body)
      r.borrowed = 0; r.total = 0
    } catch (e) { ElMessage.error(`${r.note} 还币失败: ${e?.detail || e?.error || e}`) }
  }
  busy.value = null
  bulkBusy.value = false
  ElMessage.success(`已对 ${need.length} 个子账户提交全额还币`)
  emit('done')
}
</script>

<style scoped lang="scss">
.rhd { font-size: 13px; font-weight: 700; color: var(--mix-t1, #EAECEF);
  .gold { color: #F0B90B; } .sub { font-style: normal; font-size: 10.5px; font-weight: 400; color: var(--mix-t3, #5E6673); margin-left: 8px; } }
.rtable { width: 100%; border-collapse: collapse; font-size: 11px;
  th { background: #0d0d14; color: var(--el-text-color-secondary); padding: 6px 8px; font-weight: 600; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--el-border-color); }
  th.tl, td.tl { text-align: left; }
  td { padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,.05); }
  tr:hover td { background: rgba(255,255,255,.03); } }
.num { text-align: right; font-family: monospace; font-variant-numeric: tabular-nums; }
.amber { color: #f59e0b; }
.ctr { text-align: center; }
.ops { white-space: nowrap; }
.cinp { width: 84px; background: #1a1a22; border: 1px solid var(--el-border-color); border-radius: 5px; padding: 3px 6px; font-size: 11px; text-align: right; color: #EAECEF;
  &:focus { outline: none; border-color: #F0B90B; } &:disabled { opacity: .4; } }
.pbtn { border: none; border-radius: 5px; padding: 3px 9px; font-size: 10px; cursor: pointer; margin-right: 4px;
  &:disabled { opacity: .4; cursor: not-allowed; }
  &.gold { background: rgba(240,185,11,.18); color: #F0B90B; &:hover:not(:disabled) { background: rgba(240,185,11,.32); } }
  &.amberb { background: rgba(245,158,11,.18); color: #f59e0b; &:hover:not(:disabled) { background: rgba(245,158,11,.32); } }
  &.green { background: rgba(14,203,129,.18); color: #0ECB81; &:hover:not(:disabled) { background: rgba(14,203,129,.32); } } }
.edim { text-align: center; color: var(--el-text-color-placeholder); padding: 20px; }
.fage { font-size: 10px; color: var(--el-text-color-placeholder); margin-top: 8px; }
.pause { margin-right: auto; display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--el-text-color-secondary); cursor: pointer; user-select: none;
  .ck { accent-color: #f59e0b; } }
</style>
