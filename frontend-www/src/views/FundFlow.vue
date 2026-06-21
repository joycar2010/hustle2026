<template>
  <div class="pb-20 md:pb-6">
    <header class="hidden md:flex border-b border-border-primary px-6 py-3 items-center justify-between sticky top-0 z-40" style="background-color: #16181F">
      <span class="font-semibold">HustleXAU · 资金流向</span>
      <div class="flex items-center gap-4">
        <span class="text-sm text-text-secondary">{{ auth.user?.username || '--' }}</span>
        <button @click="$router.push('/')" class="text-sm text-text-tertiary hover:text-text-primary">返回总览</button>
      </div>
    </header>
    <div class="md:hidden bg-dark-100 border-b border-border-primary px-4 py-3 flex items-center justify-between">
      <span class="font-semibold text-sm flex-shrink-0">资金流向</span>
      <span class="text-xs text-text-secondary truncate">{{ auth.user?.username || '--' }}</span>
    </div>

    <div v-if="maintenanceActive" class="px-4 py-16 md:px-6 md:py-24 max-w-5xl mx-auto text-center">
      <div class="text-6xl mb-4">🛠</div>
      <div class="text-xl font-semibold mb-2">系统维护中</div>
      <div class="text-sm text-text-tertiary">{{ maintenanceReason || '资金数据暂不可用' }}</div>
      <div v-if="maintenanceResume" class="text-sm text-text-tertiary mt-1">预计 {{ new Date(maintenanceResume).toLocaleString('zh-CN', { hour12: false }) }} 恢复</div>
    </div>

    <div v-else-if="!permAllowed" class="px-4 py-16 md:px-6 md:py-24 max-w-5xl mx-auto text-center">
      <div class="text-6xl mb-4">🔒</div>
      <div class="text-xl font-semibold mb-2">查看资金权限未开启</div>
      <div class="text-sm text-text-tertiary">请联系管理员在用户管理中为您开启「查看资金」权限。</div>
    </div>

    <div v-else class="px-4 py-4 md:px-6 md:py-6 max-w-5xl mx-auto">
      <div class="bg-dark-100 rounded-2xl border border-border-primary p-3 md:p-4">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
          <span class="text-sm font-bold">资金流向</span>
          <div class="flex items-center gap-1.5 flex-shrink-0">
            <select v-if="viewOptions.length > 1" v-model="activeView" @change="loadFundFlow"
              class="bg-dark-200 border border-border-primary rounded text-xs px-2 py-1 max-w-[40vw]">
              <option v-for="o in viewOptions" :key="o.val" :value="o.val">{{ o.label }}</option>
            </select>
            <select v-model.number="fundFlowDays" @change="loadFundFlow"
              class="bg-dark-200 border border-border-primary rounded text-xs px-2 py-1">
              <option :value="7">7 天</option>
              <option :value="30">30 天</option>
              <option :value="90">90 天</option>
            </select>
            <button @click="loadFundFlow" :disabled="fundFlowLoading"
              class="text-xs px-2 py-1 bg-dark-200 border border-border-primary rounded hover:border-primary disabled:opacity-40 whitespace-nowrap">
              {{ fundFlowLoading ? '刷新中' : '🔄 刷新' }}
            </button>
          </div>
        </div>
        <div v-if="fundFlowLoading && !fundFlows.length" class="py-8 text-center text-text-tertiary text-sm">加载中…</div>
        <div v-else-if="!fundFlows.length" class="py-8 text-center text-text-tertiary text-sm">近 {{ fundFlowDays }} 天无划转 / 充值 / 提现记录</div>
        <div v-else>
          <div class="hidden md:block max-h-[70vh] overflow-y-auto">
            <table class="w-full text-xs">
              <thead class="text-text-tertiary">
                <tr class="text-left border-b border-border-primary">
                  <th class="py-2 pr-2">时间</th>
                  <th class="py-2 pr-2">平台</th>
                  <th class="py-2 pr-2">账户</th>
                  <th class="py-2 pr-2">类型</th>
                  <th class="py-2 pr-2 text-right">金额</th>
                  <th class="py-2 text-right">币种</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(f, i) in fundFlows" :key="i" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-1.5 pr-2 text-text-tertiary whitespace-nowrap">{{ fmtFlowTime(f.timestamp) }}</td>
                  <td class="py-1.5 pr-2 text-text-secondary">{{ f.platform }}</td>
                  <td class="py-1.5 pr-2 text-text-primary truncate max-w-[200px]">{{ f.account_name }}</td>
                  <td class="py-1.5 pr-2">
                    <span class="px-1 py-0.5 rounded text-[10px]"
                      :class="f.direction === 'in' ? 'bg-[#0ecb81]/20 text-[#0ecb81]' : 'bg-[#f6465d]/20 text-[#f6465d]'">
                      {{ flowTypeLabel(f.type) }}
                    </span>
                  </td>
                  <td class="py-1.5 pr-2 text-right font-mono"
                    :class="f.direction === 'in' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                    {{ f.direction === 'in' ? '+' : '' }}{{ parseFloat(f.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
                  </td>
                  <td class="py-1.5 text-right text-text-tertiary">{{ f.asset }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="md:hidden max-h-[80vh] overflow-y-auto space-y-2">
            <div v-for="(f, i) in fundFlows" :key="i"
              class="bg-dark-200 rounded-lg p-2.5 border border-border-secondary">
              <div class="flex items-center justify-between mb-1">
                <div class="flex items-center gap-1.5 min-w-0 flex-1">
                  <span class="px-1.5 py-0.5 rounded text-[10px] flex-shrink-0"
                    :class="f.direction === 'in' ? 'bg-[#0ecb81]/20 text-[#0ecb81]' : 'bg-[#f6465d]/20 text-[#f6465d]'">
                    {{ flowTypeLabel(f.type) }}
                  </span>
                  <span class="text-[10px] text-text-tertiary flex-shrink-0">{{ f.platform }}</span>
                </div>
                <span class="font-mono text-sm font-semibold flex-shrink-0 ml-2"
                  :class="f.direction === 'in' ? 'text-[#0ecb81]' : 'text-[#f6465d]'">
                  {{ f.direction === 'in' ? '+' : '' }}{{ parseFloat(f.amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
                  <span class="text-[10px] text-text-tertiary font-normal">{{ f.asset }}</span>
                </span>
              </div>
              <div class="flex items-center justify-between text-[10px]">
                <span class="text-text-secondary truncate pr-2 min-w-0 flex-1">{{ f.account_name }}</span>
                <span class="text-text-tertiary whitespace-nowrap flex-shrink-0">{{ fmtFlowTime(f.timestamp) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="fundFlowErrors" class="mt-2 text-[10px] text-[#f0b90b]">部分账户查询异常：{{ fundFlowErrors }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useMaintenance } from '@/composables/useMaintenance.js'
import { useAuthStore } from '@/stores/auth.js'
import api from '@/services/api.js'
import { fetchFundFlow, setWsInstance } from '@/utils/pnlUtils.js'
import { useWebSocket } from '@/composables/useWebSocket.js'
import dayjs from 'dayjs'

const { maintenanceActive, maintenanceReason, maintenanceResume } = useMaintenance()
const auth = useAuthStore()

const permAllowed = ref(true)
const fundFlows = ref([])
const fundFlowLoading = ref(false)
const fundFlowDays = ref(30)
const fundFlowErrors = ref('')
const { connected: wsConnected, connect: wsConnect, disconnect: wsDisconnect, requestData } = useWebSocket()

// 收益关联(20260621): 资金流向同收益页, 加视图下拉(合并全部/各用户)
const activeView = ref('merged')
const viewOptions = ref([])
async function loadViewOptions() {
  try {
    const r = await api.get('/api/v1/pnl/link-options')
    const linked = r.data?.linked || []
    if (linked.length === 0) { viewOptions.value = []; return }
    const self = r.data?.self
    viewOptions.value = [
      { label: '合并全部数据', val: 'merged' },
      ...(self ? [{ label: self.username + '(本人)', val: self.user_id }] : []),
      ...linked.map(u => ({ label: u.username, val: u.user_id })),
    ]
  } catch (e) { viewOptions.value = [] }
}

async function loadFundFlow() {
  fundFlowLoading.value = true
  try {
    const r = await fetchFundFlow(fundFlowDays.value, activeView.value)
    fundFlows.value = r?.flows || []
    const errs = r?.errors || {}
    const errKeys = Object.keys(errs)
    fundFlowErrors.value = errKeys.length ? errKeys.map(k => errs[k]).join('; ') : ''
    permAllowed.value = true
  } catch (e) {
    fundFlows.value = []
    // Any non-2xx on this endpoint means we can't view → hide the module entirely.
    // Only "部分账户查询异常" (inline errors) ever fires from a successful 2xx response
    // that carries a per-account errors dict.
    const st = e.response?.status
    if (st === 401 || st === 403 || st >= 500) {
      permAllowed.value = false
      fundFlowErrors.value = ''
    } else {
      fundFlowErrors.value = (e.response?.data?.detail || e.message || '').toString()
    }
  } finally {
    fundFlowLoading.value = false
  }
}

function flowTypeLabel(t) {
  const map = {
    transfer: '划转', transfer_in: '转入', transfer_out: '转出',
    internal_transfer: '内部划转', internal_deposit: '内部转入', internal_withdraw: '内部转出',
    deposit: '充值', withdraw: '提现', withdrawal: '提现',
    welcome_bonus: '赠金', bonus: '赠金', bonus_recollect: '赠金回收',
  }
  return map[t] || t
}
function fmtFlowTime(ts) {
  if (!ts) return '--'
  return dayjs(ts).format('MM-DD HH:mm')
}

onUnmounted(() => wsDisconnect())
onMounted(() => {
  wsConnect()
  setWsInstance({ connected: wsConnected, requestData })
  loadViewOptions()   // 加载视图下拉(有关联用户才显示)
  loadFundFlow()
})
</script>
