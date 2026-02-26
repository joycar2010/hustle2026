<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">挂单查询</h1>

    <!-- Filters -->
    <div class="card mb-6">
      <div class="flex flex-wrap items-center gap-4">
        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">来源:</label>
          <select
            v-model="filterSource"
            class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
          >
            <option value="">全部</option>
            <option value="strategy">策略交易</option>
            <option value="manual">人工操作</option>
          </select>
        </div>

        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-400">状态:</label>
          <select
            v-model="filterStatus"
            class="px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
          >
            <option value="new,pending">挂单中</option>
            <option value="">全部状态</option>
            <option value="filled">已成交</option>
            <option value="canceled,cancelled">已取消</option>
          </select>
        </div>

        <button @click="fetchOrders" class="btn-primary">
          刷新
        </button>
      </div>
    </div>

    <!-- Orders Table -->
    <div class="card">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 border-b border-gray-700">
              <th class="pb-3">时间</th>
              <th class="pb-3">平台</th>
              <th class="pb-3">交易对</th>
              <th class="pb-3">方向</th>
              <th class="pb-3">数量</th>
              <th class="pb-3">价格</th>
              <th class="pb-3">状态</th>
              <th class="pb-3">来源</th>
              <th class="pb-3">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="orders.length === 0">
              <td colspan="9" class="text-center py-8 text-gray-500">暂无数据</td>
            </tr>
            <tr v-for="order in orders" :key="order.id" class="border-b border-gray-800">
              <td class="py-3">{{ formatDateTime(order.timestamp) }}</td>
              <td class="text-xs text-gray-400">{{ order.exchange }}</td>
              <td>{{ order.symbol }}</td>
              <td>
                <span :class="order.side === 'buy' ? 'text-green-500' : 'text-red-500'">
                  {{ order.side === 'buy' ? '买入' : '卖出' }}
                </span>
              </td>
              <td>{{ order.quantity }}</td>
              <td>{{ order.price != null ? Number(order.price).toFixed(2) : '-' }}</td>
              <td>
                <span :class="getStatusClass(order.status)">
                  {{ getStatusText(order.status) }}
                </span>
              </td>
              <td>
                <span class="text-xs px-2 py-1 rounded" :class="getSourceClass(order.source)">
                  {{ getSourceText(order.source) }}
                </span>
              </td>
              <td>
                <button
                  v-if="order.status === 'new' || order.status === 'pending'"
                  @click="manualProcessOrder(order.id)"
                  class="text-xs px-3 py-1 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors"
                >
                  人工补单
                </button>
                <span v-else class="text-xs text-gray-500">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import api from '@/services/api'

const orders = ref([])
const filterSource = ref('')
const filterStatus = ref('new,pending')

onMounted(() => {
  fetchOrders()
})

watch([filterSource, filterStatus], () => {
  fetchOrders()
})

async function fetchOrders() {
  try {
    const params = { limit: 200 }
    if (filterSource.value) {
      params.source = filterSource.value
    }
    if (filterStatus.value) {
      params.status = filterStatus.value
    }
    const response = await api.get('/api/v1/trading/orders', { params })
    orders.value = response.data
  } catch (error) {
    console.error('Failed to fetch orders:', error)
  }
}

async function manualProcessOrder(orderId) {
  if (!confirm('确定要将此订单标记为已人工处理吗？')) return

  try {
    await api.post(`/api/v1/trading/orders/${orderId}/manual-process`)
    alert('订单已标记为人工处理')
    await fetchOrders()
  } catch (error) {
    console.error('Failed to process order:', error)
    alert('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function formatDateTime(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function getStatusClass(status) {
  const classes = {
    new: 'text-yellow-500',
    pending: 'text-yellow-500',
    filled: 'text-green-500',
    canceled: 'text-red-500',
    cancelled: 'text-red-500',
    manually_processed: 'text-blue-500',
  }
  return classes[status] || 'text-gray-400'
}

function getStatusText(status) {
  const texts = {
    new: '挂单中',
    pending: '挂单中',
    filled: '已成交',
    canceled: '已取消',
    cancelled: '已取消',
    manually_processed: '已人工处理',
  }
  return texts[status] || status
}

function getSourceClass(source) {
  const classes = {
    manual: 'bg-blue-500/20 text-blue-400',
    strategy: 'bg-purple-500/20 text-purple-400',
    sync: 'bg-gray-500/20 text-gray-400',
  }
  return classes[source] || 'bg-gray-500/20 text-gray-400'
}

function getSourceText(source) {
  const texts = {
    manual: '人工',
    strategy: '策略',
    sync: '同步',
  }
  return texts[source] || source
}
</script>
