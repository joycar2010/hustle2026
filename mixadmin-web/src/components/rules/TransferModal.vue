<template>
  <el-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)"
             width="460" class="transfermodal">
    <template #header>
      <div class="tabs">
        <span class="tab" :class="{on: mode==='internal'}" @click="mode='internal'">内部划转</span>
        <span class="tab" :class="{on: mode==='cross'}" @click="mode='cross'">跨账户划转</span>
      </div>
    </template>
    <div class="body">
      <div class="frow">
        <label>{{ mode==='cross' ? '本账户' : '账户' }}</label>
        <select v-model="anchor" class="sel">
          <option v-for="a in accounts" :key="a.sub" :value="a.sub">{{ a.note }} (#{{ a.sub }})</option>
        </select>
      </div>
      <div v-if="bal" class="balbox">
        <span>杠杆可用 <b>{{ n(bal.margin_usdt_free) }}</b></span>
        <span>合约余额 <b>{{ n(bal.futures_total) }}</b></span>
        <span>合约可用 <b>{{ n(bal.futures_available) }}</b></span>
      </div>

      <template v-if="mode==='internal'">
        <div class="grid2">
          <div class="frow"><label>源钱包</label>
            <select v-model="fromWallet" class="sel"><option v-for="w in WALLETS" :key="w.v" :value="w.v">{{ w.l }}</option></select></div>
          <div class="frow"><label>目标钱包</label>
            <select v-model="toWallet" class="sel"><option v-for="w in WALLETS" :key="w.v" :value="w.v">{{ w.l }}</option></select></div>
        </div>
      </template>
      <template v-else>
        <div class="grid2">
          <div class="frow"><label>方向</label>
            <select v-model="crossDir" class="sel"><option value="out">本账户转出</option><option value="in">本账户转入</option></select></div>
          <div class="frow"><label>对手账户</label>
            <select v-model="cpType" class="sel"><option value="master">主账户</option><option value="sub">其他子账户</option></select></div>
        </div>
        <div v-if="cpType==='sub'" class="frow"><label>对手子账户</label>
          <select v-model="cpSub" class="sel">
            <option :value="null">选择对手子账户</option>
            <option v-for="a in others" :key="a.sub" :value="a.sub">{{ a.note }} (#{{ a.sub }})</option>
          </select></div>
        <div class="flowline"><span class="src">{{ srcLabel }}</span><span class="arr">→</span><span class="dst">{{ dstLabel }}</span></div>
        <div class="grid2">
          <div class="frow"><label>源钱包</label>
            <select v-model="fromWallet" class="sel"><option v-for="w in WALLETS" :key="w.v" :value="w.v">{{ w.l }}</option></select></div>
          <div class="frow"><label>目标钱包</label>
            <select v-model="toWallet" class="sel"><option v-for="w in WALLETS" :key="w.v" :value="w.v">{{ w.l }}</option></select></div>
        </div>
        <p class="note">经主账户万向划转(需主账户开启「万向划转」权限)；主↔子、子↔子均可。</p>
      </template>

      <div class="grid2">
        <div class="frow"><label>资产</label><input v-model="asset" class="inp" @input="asset = asset.toUpperCase()" /></div>
        <div class="frow"><label>金额</label><input v-model="amount" class="inp" type="number" placeholder="0.00" /></div>
      </div>
      <p v-if="err" class="errline">{{ err }}</p>
      <p v-if="ok" class="okline">{{ ok }}</p>
    </div>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">关闭</el-button>
      <el-button type="warning" :loading="loading"
                 :disabled="mode==='internal' && fromWallet===toWallet"
                 @click="submit">{{ loading ? '划转中...' : `划转 ${asset}` }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { mixApi } from '../../api/mix'

const props = defineProps({
  modelValue: Boolean,
  accounts: { type: Array, default: () => [] },   // [{sub, note, balance?}]
  defaultSub: { type: [Number, String], default: null },
  symbol: { type: String, default: 'USDT' },      // 路径币仅作 API 载体
})
const emit = defineEmits(['update:modelValue', 'done'])

const WALLETS = [{ v: 'margin', l: '杠杆账户' }, { v: 'spot', l: '现货账户' }, { v: 'futures', l: '合约账户' }]
const mode = ref('internal')
const anchor = ref(null)
const fromWallet = ref('futures'); const toWallet = ref('margin')
const crossDir = ref('out'); const cpType = ref('master'); const cpSub = ref(null)
const asset = ref('USDT'); const amount = ref('')
const loading = ref(false); const err = ref(''); const ok = ref('')

watch(() => props.modelValue, v => {
  if (v) {
    err.value = ''; ok.value = ''; amount.value = ''
    anchor.value = props.defaultSub ?? props.accounts[0]?.sub ?? null
  }
})
const bal = computed(() => props.accounts.find(a => a.sub === anchor.value)?.balance || null)
const others = computed(() => props.accounts.filter(a => a.sub !== anchor.value))
const noteOf = s => props.accounts.find(a => a.sub === s)?.note || `#${s}`
const cpLabel = computed(() => cpType.value === 'master' ? '主账户' : (cpSub.value ? noteOf(cpSub.value) : '对手子账户'))
const srcLabel = computed(() => crossDir.value === 'out' ? noteOf(anchor.value) : cpLabel.value)
const dstLabel = computed(() => crossDir.value === 'out' ? cpLabel.value : noteOf(anchor.value))
const n = v => (v == null ? '—' : Math.round(parseFloat(v) * 100) / 100)

async function submit() {
  err.value = ''; ok.value = ''
  const amt = parseFloat(amount.value)
  if (!amt || amt <= 0) { err.value = '请输入有效金额'; return }
  if (mode.value === 'cross' && cpType.value === 'sub' && !cpSub.value) { err.value = '请选择对手子账户'; return }
  loading.value = true
  try {
    const body = mode.value === 'internal'
      ? { action: 'transfer', sub: anchor.value, from_wallet: fromWallet.value, to_wallet: toWallet.value, asset: asset.value, amount: amt }
      : { action: 'transfer_cross', sub: anchor.value, direction: crossDir.value, counterparty_type: cpType.value,
          counterparty_sub: cpType.value === 'sub' ? cpSub.value : undefined,
          from_wallet: fromWallet.value, to_wallet: toWallet.value, asset: asset.value, amount: amt }
    const r = await mixApi.coinMenu(props.symbol || 'USDT', body)
    ok.value = r?.coin?.message || '划转成功（coin 权威执行）'
    amount.value = ''
    emit('done')
  } catch (e) { err.value = e?.detail || e?.error || '划转失败' }
  finally { loading.value = false }
}
</script>

<style scoped lang="scss">
.tabs { display: flex; gap: 14px; }
.tab { font-size: 13px; font-weight: 700; color: var(--el-text-color-secondary); cursor: pointer; padding-bottom: 3px;
  &.on { color: #F0B90B; border-bottom: 2px solid #F0B90B; } }
.body { display: flex; flex-direction: column; gap: 10px; }
.frow { display: flex; flex-direction: column; gap: 4px; flex: 1;
  label { font-size: 10.5px; color: var(--el-text-color-secondary); } }
.grid2 { display: flex; gap: 10px; }
.sel, .inp { background: #12151A; border: 1px solid var(--el-border-color); border-radius: 6px; color: #EAECEF; font-size: 12px; padding: 6px 8px; width: 100%;
  &:focus { outline: none; border-color: #F0B90B; } }
.balbox { display: flex; gap: 14px; border: 1px solid var(--el-border-color); border-radius: 6px; padding: 7px 10px; font-size: 10.5px; color: var(--el-text-color-secondary);
  b { color: #EAECEF; font-family: monospace; margin-left: 4px; } }
.flowline { display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 12px;
  .src { padding: 3px 10px; border: 1px solid rgba(240,185,11,.3); background: rgba(240,185,11,.1); color: #F0B90B; border-radius: 5px; }
  .arr { color: #F0B90B; }
  .dst { padding: 3px 10px; border: 1px solid rgba(14,203,129,.3); background: rgba(14,203,129,.1); color: #0ECB81; border-radius: 5px; } }
.note { font-size: 10px; color: var(--el-text-color-placeholder); margin: 0; }
.errline { color: #F6465D; font-size: 11.5px; margin: 0; }
.okline { color: #0ECB81; font-size: 11.5px; margin: 0; }
</style>
