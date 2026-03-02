<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">策略控制</h1>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
      <div class="card">
        <div class="text-sm text-text-secondary mb-1">运行中策略</div>
        <div class="text-3xl font-bold text-success">{{ runningCount }}</div>
      </div>
      <div class="card">
        <div class="text-sm text-text-secondary mb-1">今日收益</div>
        <div class="text-3xl font-bold text-primary">{{ todayProfit.toFixed(2) }} USDT</div>
      </div>
      <div class="card">
        <div class="text-sm text-text-secondary mb-1">总策略数</div>
        <div class="text-3xl font-bold">{{ strategies.length }}</div>
      </div>
    </div>

    <div class="card mb-6">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-bold">自动化策略</h2>
        <button @click="openCreateModal" class="btn-primary">
          <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
          创建策略
        </button>
      </div>

      <div class="space-y-4">
        <div v-for="strategy in strategies" :key="strategy.id" class="bg-dark-200 rounded-lg p-4">
          <div class="flex justify-between items-start mb-3">
            <div class="flex-1">
              <div class="flex items-center space-x-3 mb-2">
                <h3 class="font-bold text-lg">{{ strategy.name }}</h3>
                <span :class="['px-3 py-1 rounded text-sm font-medium', getStatusClass(strategy.status)]">
                  {{ getStatusText(strategy.status) }}
                </span>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <span class="text-text-secondary">类型:</span>
                  <span class="ml-2 font-medium">{{ strategy.type === 'reverse' ? '反向套利' : '正向套利' }}</span>
                </div>
                <div>
                  <span class="text-text-secondary">M币:</span>
                  <span class="ml-2 font-medium">{{ strategy.m_coin }}</span>
                </div>
                <div>
                  <span class="text-text-secondary">开仓:</span>
                  <span :class="['ml-2 font-medium', strategy.opening_enabled ? 'text-success' : 'text-danger']">
                    {{ strategy.opening_enabled ? '启用' : '禁用' }}
                  </span>
                </div>
                <div>
                  <span class="text-text-secondary">平仓:</span>
                  <span :class="['ml-2 font-medium', strategy.closing_enabled ? 'text-success' : 'text-danger']">
                    {{ strategy.closing_enabled ? '启用' : '禁用' }}
                  </span>
                </div>
              </div>
            </div>
            <div class="flex items-center space-x-2 ml-4">
              <button @click="openEditModal(strategy)" class="btn-secondary text-sm">
                编辑
              </button>
              <button @click="toggleStrategy(strategy)" :class="strategy.status === 'running' ? 'btn-danger text-sm' : 'btn-success text-sm'">
                {{ strategy.status === 'running' ? '停止' : '启动' }}
              </button>
              <button @click="deleteStrategy(strategy.id)" class="btn-secondary text-sm text-danger">
                删除
              </button>
            </div>
          </div>

          <div class="mt-3 pt-3 border-t border-border-secondary">
            <div class="flex items-center justify-between text-sm">
              <span class="text-text-secondary">梯度配置:</span>
              <span class="font-medium">{{ strategy.ladders?.length || 0 }} 个梯度</span>
            </div>
            <div v-if="strategy.ladders && strategy.ladders.length > 0" class="mt-2 space-y-1">
              <div v-for="(ladder, index) in strategy.ladders" :key="index" class="flex items-center justify-between text-xs bg-dark-100 rounded px-3 py-2">
                <span :class="ladder.enabled ? 'text-success' : 'text-text-secondary'">
                  梯度{{ index + 1 }}: {{ ladder.enabled ? '启用' : '禁用' }}
                </span>
                <span class="text-text-secondary">
                  开仓价: {{ ladder.open_price }} USDT | 阈值: {{ ladder.threshold }} | 数量: {{ ladder.qty_limit }}
                </span>
              </div>
            </div>
          </div>

          <div class="mt-3 pt-3 border-t border-border-secondary grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <span class="text-text-secondary">今日交易:</span>
              <span class="ml-2 font-bold">{{ strategy.today_trades || 0 }}</span>
            </div>
            <div>
              <span class="text-text-secondary">今日收益:</span>
              <span :class="['ml-2 font-bold', (strategy.today_profit || 0) >= 0 ? 'text-success' : 'text-danger']">
                {{ (strategy.today_profit || 0).toFixed(2) }} USDT
              </span>
            </div>
            <div>
              <span class="text-text-secondary">总收益:</span>
              <span :class="['ml-2 font-bold', (strategy.total_profit || 0) >= 0 ? 'text-success' : 'text-danger']">
                {{ (strategy.total_profit || 0).toFixed(2) }} USDT
              </span>
            </div>
          </div>
        </div>

        <div v-if="strategies.length === 0" class="text-center py-12 text-text-secondary">
          <svg class="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p>暂无策略，点击"创建策略"开始</p>
        </div>
      </div>
    </div>

    <div v-if="showModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4" @click.self="closeModal">
      <div class="bg-dark-200 rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-xl font-bold mb-4">{{ isEditMode ? '编辑策略' : '创建策略' }}</h3>
        <form @submit.prevent="saveStrategy">
          <div class="space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-sm font-medium mb-1">策略名称</label>
                <input v-model="strategyForm.name" type="text" required class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
              </div>
              <div>
                <label class="block text-sm font-medium mb-1">策略类型</label>
                <select v-model="strategyForm.type" class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                  <option value="reverse">反向套利</option>
                  <option value="forward">正向套利</option>
                </select>
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label class="block text-sm font-medium mb-1">M币设置</label>
                <input v-model.number="strategyForm.m_coin" type="number" required class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary" />
              </div>
              <div class="flex items-center pt-6">
                <input v-model="strategyForm.opening_enabled" type="checkbox" id="opening_enabled" class="mr-2" />
                <label for="opening_enabled" class="text-sm">启用开仓</label>
              </div>
              <div class="flex items-center pt-6">
                <input v-model="strategyForm.closing_enabled" type="checkbox" id="closing_enabled" class="mr-2" />
                <label for="closing_enabled" class="text-sm">启用平仓</label>
              </div>
            </div>

            <div class="border-t border-border-secondary pt-4">
              <div class="flex justify-between items-center mb-3">
                <h4 class="font-bold">梯度配置</h4>
                <button type="button" @click="addLadder" :disabled="strategyForm.ladders.length >= 5" class="btn-secondary text-sm">
                  添加梯度
                </button>
              </div>
              <div class="space-y-3">
                <div v-for="(ladder, index) in strategyForm.ladders" :key="index" class="bg-dark-100 rounded p-3">
                  <div class="flex justify-between items-center mb-2">
                    <div class="flex items-center">
                      <input v-model="ladder.enabled" type="checkbox" :id="`ladder_${index}`" class="mr-2" />
                      <label :for="`ladder_${index}`" class="text-sm font-medium">梯度 {{ index + 1 }}</label>
                    </div>
                    <button type="button" @click="removeLadder(index)" class="text-danger text-sm hover:text-red-400">删除</button>
                  </div>
                  <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label class="block text-xs text-text-secondary mb-1">开仓价</label>
                      <input v-model.number="ladder.open_price" type="number" step="0.01" class="w-full px-2 py-1 text-sm bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary" />
                    </div>
                    <div>
                      <label class="block text-xs text-text-secondary mb-1">阈值</label>
                      <input v-model.number="ladder.threshold" type="number" step="0.1" class="w-full px-2 py-1 text-sm bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary" />
                    </div>
                    <div>
                      <label class="block text-xs text-text-secondary mb-1">数量限制</label>
                      <input v-model.number="ladder.qty_limit" type="number" step="0.01" class="w-full px-2 py-1 text-sm bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="flex justify-end space-x-3 mt-6">
            <button type="button" @click="closeModal" class="btn-secondary">取消</button>
            <button type="submit" class="btn-primary">保存</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '@/services/api'

const strategies = ref([])
const showModal = ref(false)
const isEditMode = ref(false)
const strategyForm = ref({
  id: null,
  name: '',
  type: 'reverse',
  m_coin: 100,
  opening_enabled: true,
  closing_enabled: true,
  ladders: [
    { enabled: true, open_price: 2650, threshold: 2.0, qty_limit: 0.1 }
  ]
})

const runningCount = computed(() => strategies.value.filter(s => s.status === 'running').length)
const todayProfit = computed(() => strategies.value.reduce((sum, s) => sum + (s.today_profit || 0), 0))

onMounted(() => {
  fetchStrategies()
})

async function fetchStrategies() {
  try {
    const response = await api.get('/api/v1/strategies/configs')
    // Map backend data structure to frontend expectations
    strategies.value = response.data.map(config => ({
      id: config.config_id,
      name: `${config.strategy_type === 'forward' ? '正向' : '反向'}套利策略`,
      type: config.strategy_type,
      status: config.is_enabled ? 'running' : 'stopped',
      m_coin: config.order_qty * 100, // Convert to display format
      opening_enabled: config.is_enabled,
      closing_enabled: config.is_enabled,
      ladders: [
        {
          enabled: config.is_enabled,
          open_price: config.target_spread,
          threshold: config.retry_times,
          qty_limit: config.order_qty
        }
      ],
      today_trades: 0,
      today_profit: 0,
      total_profit: 0,
      // Store original config for editing
      _config: config
    }))
  } catch (error) {
    console.error('Failed to fetch strategies:', error)
    alert('获取策略列表失败: ' + (error.response?.data?.detail || error.message))
    strategies.value = []
  }
}

function openCreateModal() {
  isEditMode.value = false
  strategyForm.value = {
    id: null,
    name: '',
    type: 'reverse',
    m_coin: 100,
    opening_enabled: true,
    closing_enabled: true,
    ladders: [
      { enabled: true, open_price: 2650, threshold: 2.0, qty_limit: 0.1 }
    ]
  }
  showModal.value = true
}

function openEditModal(strategy) {
  isEditMode.value = true
  strategyForm.value = JSON.parse(JSON.stringify(strategy))
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

async function saveStrategy() {
  try {
    // Map frontend form data to backend structure
    const configData = {
      strategy_type: strategyForm.value.type,
      target_spread: strategyForm.value.ladders[0]?.open_price || 2650,
      order_qty: strategyForm.value.ladders[0]?.qty_limit || 0.1,
      retry_times: Math.floor(strategyForm.value.ladders[0]?.threshold || 2),
      mt5_stuck_threshold: 5,
      is_enabled: strategyForm.value.opening_enabled
    }

    if (isEditMode.value) {
      await api.put(`/api/v1/strategies/configs/${strategyForm.value.id}`, configData)
      alert('策略更新成功')
    } else {
      await api.post('/api/v1/strategies/configs', configData)
      alert('策略创建成功')
    }
    await fetchStrategies()
    closeModal()
  } catch (error) {
    console.error('Failed to save strategy:', error)
    alert('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function toggleStrategy(strategy) {
  try {
    const newStatus = strategy.status !== 'running'
    await api.put(`/api/v1/strategies/configs/${strategy.id}`, {
      is_enabled: newStatus
    })
    await fetchStrategies()
    alert(`策略已${newStatus ? '启动' : '停止'}`)
  } catch (error) {
    console.error('Failed to toggle strategy:', error)
    alert('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function deleteStrategy(strategyId) {
  if (!confirm('确定要删除此策略吗？')) return
  try {
    await api.delete(`/api/v1/strategies/configs/${strategyId}`)
    await fetchStrategies()
    alert('策略已删除')
  } catch (error) {
    console.error('Failed to delete strategy:', error)
    alert('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

function addLadder() {
  if (strategyForm.value.ladders.length < 5) {
    strategyForm.value.ladders.push({
      enabled: true,
      open_price: 2650,
      threshold: 2.0,
      qty_limit: 0.1
    })
  }
}

function removeLadder(index) {
  strategyForm.value.ladders.splice(index, 1)
}

function getStatusClass(status) {
  return status === 'running' ? 'bg-success/20 text-success' : 'bg-gray-500/20 text-gray-400'
}

function getStatusText(status) {
  return status === 'running' ? '运行中' : '已停止'
}
</script>

<style scoped>
.btn-primary {
  @apply inline-flex items-center px-4 py-2 bg-primary hover:bg-primary-hover text-dark-300 rounded-lg transition-colors font-medium;
}

.btn-secondary {
  @apply inline-flex items-center px-4 py-2 bg-dark-200 hover:bg-dark-100 text-text-primary rounded-lg transition-colors font-medium;
}

.btn-success {
  @apply inline-flex items-center px-4 py-2 bg-success hover:bg-green-600 text-white rounded-lg transition-colors font-medium;
}

.btn-danger {
  @apply inline-flex items-center px-4 py-2 bg-danger hover:bg-red-600 text-white rounded-lg transition-colors font-medium;
}

.card {
  @apply bg-dark-200 rounded-lg p-6 shadow-lg;
}
</style>
