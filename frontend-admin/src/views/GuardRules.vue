<template>
  <div class="guard-page">
    <div class="page-head">
      <h1 class="text-2xl font-bold">Guard 时段规则</h1>
      <p class="text-text-secondary text-sm mt-1">周一开盘 / 周三三倍过夜 / 周五周末 时段风控规则（真生效，约 5 秒内热加载）</p>
    </div>

    <div class="space-y-4 mt-4">

      <!-- 实时状态条 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary px-4 py-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            <span class="text-sm font-medium">当前时段</span>
            <span class="text-xs font-mono text-primary">{{ guardCurrentBJT }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded text-xs font-medium" :class="guardActivePhase.class">{{ guardActivePhase.label }}</span>
            <button @click="loadGuardRules" class="text-xs text-primary hover:text-primary-hover ml-3">刷新</button>
          </div>
        </div>
      </div>

      <!-- 卡片1: 周一开盘规则 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
        <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-sm font-bold">周一开盘</span>
            <span class="text-xs text-text-tertiary">06:00-08:00 BJT</span>
          </div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" v-model="guardRules.monday_open.enabled" @change="guardDirty=true" class="accent-primary">
              <span class="text-xs">启用</span>
            </label>
            <button v-if="!guardEditMode.monday" @click="guardEditMode.monday=true" class="text-xs px-2 py-1 bg-dark-200 hover:bg-dark-50 rounded">编辑</button>
            <button v-else @click="saveGuardRules(); guardEditMode.monday=false" class="text-xs px-2 py-1 bg-primary hover:bg-primary-hover text-dark-300 rounded font-medium">保存</button>
          </div>
        </div>
        <div class="p-4 space-y-3">
          <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label class="text-[10px] text-text-tertiary block mb-1">高波动开始</label>
              <input :disabled="!guardEditMode.monday" v-model="guardRules.monday_open.volatility_start" @input="guardDirty=true"
                class="w-full px-2 py-1 bg-dark-200 border border-border-primary rounded text-xs font-mono disabled:opacity-50">
            </div>
            <div>
              <label class="text-[10px] text-text-tertiary block mb-1">高波动结束</label>
              <input :disabled="!guardEditMode.monday" v-model="guardRules.monday_open.volatility_end" @input="guardDirty=true"
                class="w-full px-2 py-1 bg-dark-200 border border-border-primary rounded text-xs font-mono disabled:opacity-50">
            </div>
            <div>
              <label class="text-[10px] text-text-tertiary block mb-1">最小开仓点差</label>
              <input :disabled="!guardEditMode.monday" type="number" step="0.5" v-model.number="guardRules.monday_open.min_spread_to_open" @input="guardDirty=true"
                class="w-full px-2 py-1 bg-dark-200 border border-border-primary rounded text-xs font-mono disabled:opacity-50">
            </div>
            <div>
              <label class="text-[10px] text-text-tertiary block mb-1">资金费最低阈值</label>
              <input :disabled="!guardEditMode.monday" type="number" step="0.001" v-model.number="guardRules.monday_open.min_funding_for_capture" @input="guardDirty=true"
                class="w-full px-2 py-1 bg-dark-200 border border-border-primary rounded text-xs font-mono disabled:opacity-50">
            </div>
          </div>
          <div class="mt-3">
            <div class="text-xs text-text-tertiary mb-2 font-medium">资金费捕获阶段</div>
            <div class="space-y-2">
              <div v-for="(ph, i) in guardRules.monday_open.funding_capture_phases || []" :key="i"
                class="grid grid-cols-5 gap-2 bg-dark-200 rounded-lg p-2">
                <div><label class="text-[9px] text-text-tertiary">开始</label><input :disabled="!guardEditMode.monday" v-model="ph.start" @input="guardDirty=true" class="w-full px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-[11px] font-mono disabled:opacity-50"></div>
                <div><label class="text-[9px] text-text-tertiary">结束</label><input :disabled="!guardEditMode.monday" v-model="ph.end" @input="guardDirty=true" class="w-full px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-[11px] font-mono disabled:opacity-50"></div>
                <div><label class="text-[9px] text-text-tertiary">点差下限</label><input :disabled="!guardEditMode.monday" type="number" step="0.5" v-model.number="ph.min_spread_entry" @input="guardDirty=true" class="w-full px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-[11px] font-mono disabled:opacity-50"></div>
                <div><label class="text-[9px] text-text-tertiary">点差上限</label><input :disabled="!guardEditMode.monday" type="number" step="0.5" v-model.number="ph.upper_spread_entry" @input="guardDirty=true" class="w-full px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-[11px] font-mono disabled:opacity-50"></div>
                <div><label class="text-[9px] text-text-tertiary">最低资金费</label><input :disabled="!guardEditMode.monday" type="number" step="0.001" v-model.number="ph.min_funding" @input="guardDirty=true" class="w-full px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-[11px] font-mono disabled:opacity-50"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 卡片2: 周三三倍过夜规则 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
        <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-sm font-bold">周三三倍过夜</span>
            <span class="text-xs text-text-tertiary">18:00 BJT 起生效</span>
          </div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" v-model="guardRules.wednesday_overnight.enabled" @change="guardDirty=true" class="accent-primary">
              <span class="text-xs">启用</span>
            </label>
            <button v-if="!guardEditMode.wednesday" @click="guardEditMode.wednesday=true" class="text-xs px-2 py-1 bg-dark-200 hover:bg-dark-50 rounded">编辑</button>
            <button v-else @click="saveGuardRules(); guardEditMode.wednesday=false" class="text-xs px-2 py-1 bg-primary hover:bg-primary-hover text-dark-300 rounded font-medium">保存</button>
          </div>
        </div>
        <div class="p-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="bg-dark-200 rounded-lg p-3 border border-border-primary">
              <div class="text-xs font-semibold text-green-400 mb-2">正向（鼓励）</div>
              <div class="space-y-2">
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">基础仓位上限</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.05" v-model.number="guardRules.wednesday_overnight.forward.base_cap_pct" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">有利条件上限</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.05" v-model.number="guardRules.wednesday_overnight.forward.favorable_cap_pct" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">有利最低点差</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.5" v-model.number="guardRules.wednesday_overnight.forward.favorable_conditions.min_spread" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">有利最低资金费</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.001" v-model.number="guardRules.wednesday_overnight.forward.favorable_conditions.min_funding" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
              </div>
            </div>
            <div class="bg-dark-200 rounded-lg p-3 border border-border-primary">
              <div class="text-xs font-semibold text-red-400 mb-2">反向（限制）</div>
              <div class="space-y-2">
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">基础仓位上限</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.05" v-model.number="guardRules.wednesday_overnight.reverse.base_cap_pct" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">有利条件上限</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.05" v-model.number="guardRules.wednesday_overnight.reverse.favorable_cap_pct" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-[10px] text-text-tertiary">有利最低点差</span>
                  <input :disabled="!guardEditMode.wednesday" type="number" step="0.5" v-model.number="guardRules.wednesday_overnight.reverse.favorable_conditions.min_spread" @input="guardDirty=true"
                    class="w-20 px-1.5 py-0.5 bg-dark-300 border border-border-primary rounded text-xs font-mono text-right disabled:opacity-50">
                </div>
              </div>
              <div class="mt-2 px-2 py-1.5 bg-dark-300 rounded text-[10px] text-text-tertiary">
                核心规则：当资金费率 ≥ 三倍掉期费成本时，取消所有限制
              </div>
            </div>
          </div>
          <div class="mt-3 flex items-center gap-3">
            <span class="text-[10px] text-text-tertiary">生效起始小时 (BJT)</span>
            <input :disabled="!guardEditMode.wednesday" type="number" min="0" max="23" v-model.number="guardRules.wednesday_overnight.start_hour" @input="guardDirty=true"
              class="w-16 px-1.5 py-0.5 bg-dark-200 border border-border-primary rounded text-xs font-mono disabled:opacity-50">
          </div>
        </div>
      </div>

      <!-- 卡片3: 周五周末规则 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
        <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-sm font-bold">周五周末</span>
            <span class="text-xs text-text-tertiary">条件双向仓位管理</span>
          </div>
          <div class="flex items-center gap-2">
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" v-model="guardRules.friday_weekend.enabled" @change="guardDirty=true" class="accent-primary">
              <span class="text-xs">启用</span>
            </label>
            <button v-if="!guardEditMode.friday" @click="guardEditMode.friday=true" class="text-xs px-2 py-1 bg-dark-200 hover:bg-dark-50 rounded">编辑</button>
            <button v-else @click="saveGuardRules(); guardEditMode.friday=false" class="text-xs px-2 py-1 bg-primary hover:bg-primary-hover text-dark-300 rounded font-medium">保存</button>
          </div>
        </div>
        <div class="p-4">
          <div class="flex items-center gap-3 mb-3">
            <span class="text-[10px] text-text-tertiary">周末持仓最低点差</span>
            <input :disabled="!guardEditMode.friday" type="number" step="0.5" v-model.number="guardRules.friday_weekend.weekend_hold_min_spread" @input="guardDirty=true"
              class="w-16 px-1.5 py-0.5 bg-dark-200 border border-border-primary rounded text-xs font-mono disabled:opacity-50">
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead><tr class="border-b border-border-secondary text-text-tertiary">
                <th class="text-left py-2 px-2">时段</th>
                <th class="text-center py-2 px-2">默认上限</th>
                <th class="text-center py-2 px-2">正向+资金费上升</th>
                <th class="text-center py-2 px-2">条件加仓</th>
              </tr></thead>
              <tbody>
                <tr class="border-b border-border-secondary">
                  <td class="py-2 px-2 font-mono">周五 22:00-00:00</td>
                  <td class="py-2 px-2 text-center">20%</td>
                  <td class="py-2 px-2 text-center text-green-400">30% (spread&gt;=3.5: 40%)</td>
                  <td class="py-2 px-2 text-center text-text-secondary">funding&gt;0: 30%</td>
                </tr>
                <tr class="border-b border-border-secondary">
                  <td class="py-2 px-2 font-mono">周六 00:00-02:00</td>
                  <td class="py-2 px-2 text-center">20%</td>
                  <td class="py-2 px-2 text-center text-green-400">funding&gt;=swap: 40%</td>
                  <td class="py-2 px-2 text-center text-red-400">反向限20%并减仓</td>
                </tr>
                <tr class="border-b border-border-secondary">
                  <td class="py-2 px-2 font-mono">周六 02:00-04:00</td>
                  <td class="py-2 px-2 text-center">10%</td>
                  <td class="py-2 px-2 text-center text-green-400">rising+spread&gt;=4: 40%</td>
                  <td class="py-2 px-2 text-center text-text-secondary">spread&gt;=3.5: 30%</td>
                </tr>
                <tr>
                  <td class="py-2 px-2 font-mono">周六 04:00+</td>
                  <td class="py-2 px-2 text-center text-red-400">禁止开仓</td>
                  <td class="py-2 px-2 text-center text-green-400">rising+spread&gt;=5: 50%</td>
                  <td class="py-2 px-2 text-center text-text-tertiary">极端条件</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 最近 Guard 拦截记录 -->
      <div class="bg-dark-100 rounded-xl border border-border-primary overflow-hidden">
        <div class="px-4 py-3 border-b border-border-secondary flex items-center justify-between">
          <span class="text-sm font-bold">最近 Guard 拦截</span>
          <button @click="loadGuardBlocks" class="text-xs text-primary hover:text-primary-hover">刷新</button>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs" v-if="guardBlocks.length">
            <thead><tr class="border-b border-border-secondary text-text-tertiary">
              <th class="text-left py-2 px-3">时间</th>
              <th class="text-left py-2 px-3">规则类型</th>
              <th class="text-left py-2 px-3">拒绝原因</th>
              <th class="text-left py-2 px-3">提案</th>
            </tr></thead>
            <tbody>
              <tr v-for="b in guardBlocks" :key="b.id" class="border-b border-border-secondary hover:bg-dark-50">
                <td class="py-2 px-3 font-mono text-text-tertiary">{{ b.time }}</td>
                <td class="py-2 px-3"><span class="px-1.5 py-0.5 rounded text-[10px] font-medium" :class="guardTypeClass(b.type)">{{ b.type }}</span></td>
                <td class="py-2 px-3 text-text-secondary max-w-[300px] truncate" :title="b.reason">{{ b.reason }}</td>
                <td class="py-2 px-3 font-mono text-text-tertiary">{{ b.action }} {{ b.qty }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="px-4 py-6 text-center text-text-tertiary text-xs">暂无时段规则拦截记录</div>
        </div>
      </div>

    </div>

    <!-- Toast -->
    <Teleport to="body">
      <div v-if="toast.show" class="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-5 py-3 rounded-xl shadow-xl text-sm font-medium"
        :class="toast.type === 'success' ? 'bg-success text-dark-300' : 'bg-danger text-white'">
        {{ toast.msg }}
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api.js'
import dayjs from 'dayjs'

const toast = ref({ show: false, type: 'success', msg: '' })
function showToast(type, msg) {
  toast.value = { show: true, type, msg }
  setTimeout(() => { toast.value.show = false }, 2600)
}

// ── Guard 时段规则 ──────────────────────────────────────────────
const guardRules = ref({
  monday_open: { enabled: true, volatility_start: '06:00', volatility_end: '06:30', min_spread_to_open: 4.0, min_funding_for_capture: 0.01, funding_capture_phases: [] },
  wednesday_overnight: { enabled: true, start_hour: 18, forward: { base_cap_pct: 0.30, favorable_cap_pct: 0.50, favorable_conditions: { min_spread: 2.0, min_funding: 0.005 } }, reverse: { base_cap_pct: 0.20, favorable_cap_pct: 0.40, favorable_conditions: { min_spread: 3.0 } } },
  friday_weekend: { enabled: true, phases: 'conditional_bidirectional', weekend_hold_min_spread: 3.0 }
})
const guardEditMode = ref({ monday: false, wednesday: false, friday: false })
const guardDirty = ref(false)
const guardBlocks = ref([])

const guardCurrentBJT = computed(() => {
  return new Date().toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' })
})

const guardActivePhase = computed(() => {
  const now = new Date()
  const bjt = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
  const wd = bjt.getDay()
  const h = bjt.getHours()
  if (wd === 1 && h >= 6 && h < 8) return { label: '周一开盘', class: 'bg-yellow-900/40 text-yellow-400' }
  if (wd === 3 && h >= 18) return { label: '周三过夜', class: 'bg-purple-900/40 text-purple-400' }
  if ((wd === 5 && h >= 22) || wd === 6) return { label: '周五周末', class: 'bg-red-900/40 text-red-400' }
  return { label: '常规交易', class: 'bg-dark-200 text-text-tertiary' }
})

async function loadGuardRules() {
  try {
    const r = await api.get('/api/v1/agent/guard-rules')
    if (r.data && Object.keys(r.data).length) {
      guardRules.value = r.data
    }
    guardDirty.value = false
  } catch (e) { console.error('Load guard rules failed', e) }
  await loadGuardBlocks()
}

async function saveGuardRules() {
  try {
    await api.put('/api/v1/agent/guard-rules', guardRules.value)
    showToast('success', 'Guard 规则已更新，5秒内生效')
    guardDirty.value = false
  } catch (e) { showToast('error', '保存失败: ' + (e.response?.data?.detail || e.message)) }
}

async function loadGuardBlocks() {
  try {
    const r = await api.get('/api/v1/agent/decisions', { params: { verdict: 'rejected', limit: 30 } })
    const items = r.data?.items || []
    guardBlocks.value = items
      .filter(d => {
        const reason = d.reject_reason || ''
        return reason.match(/monday_|wed_overnight|wed_evening|friday_weekend/)
      })
      .slice(0, 15)
      .map(d => ({
        id: d.id,
        time: d.created_at ? dayjs(d.created_at).format('MM-DD HH:mm') : '--',
        type: (d.reject_reason || '').startsWith('monday_') ? '周一' : (d.reject_reason || '').startsWith('wed_') ? '周三' : '周五',
        reason: d.reject_reason || '--',
        action: d.proposal?.action || '--',
        qty: d.proposal?.qty || '--',
      }))
  } catch { guardBlocks.value = [] }
}

function guardTypeClass(type) {
  if (type === '周一') return 'bg-yellow-900/30 text-yellow-400'
  if (type === '周三') return 'bg-purple-900/30 text-purple-400'
  return 'bg-red-900/30 text-red-400'
}

onMounted(loadGuardRules)
</script>

<style scoped>
.guard-page { padding: 20px; min-height: 100vh; background: #1a1d23; }
.page-head { margin-bottom: 8px; }
</style>
