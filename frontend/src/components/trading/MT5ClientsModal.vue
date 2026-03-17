<template>
  <div v-if="show" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 rounded-lg max-w-5xl w-full max-h-[90vh] overflow-y-auto">
      <div class="p-6">
        <!-- Header -->
        <div class="flex justify-between items-center mb-6">
          <div>
            <h2 class="text-2xl font-bold">MT5 客户端管理</h2>
            <p class="text-sm text-gray-400 mt-1">账户: {{ account?.account_name }}</p>
          </div>
          <div class="flex gap-2">
            <button @click="openAddClientModal" class="btn-primary">
              + 新增客户端
            </button>
            <button @click="close" class="text-gray-400 hover:text-white">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Clients List -->
        <div v-if="loading" class="text-center py-8">
          <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          <p class="text-gray-400 mt-2">加载中...</p>
        </div>

        <div v-else-if="clients.length === 0" class="text-center py-12">
          <div class="text-gray-500 mb-4">暂无MT5客户端</div>
          <button @click="openAddClientModal" class="btn-primary">
            + 新增第一个客户端
          </button>
        </div>

        <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div v-for="client in clients" :key="client.client_id"
               class="card border"
               :class="getClientBorderClass(client)">
            <!-- Client Header -->
            <div class="flex justify-between items-start mb-3">
              <div>
                <h3 class="text-lg font-bold">{{ client.client_name }}</h3>
                <div class="flex items-center gap-2 mt-1">
                  <span class="text-xs px-2 py-1 rounded"
                        :class="getStatusClass(client.connection_status)">
                    {{ getStatusText(client.connection_status) }}
                  </span>
                  <span v-if="!client.is_active" class="text-xs px-2 py-1 bg-gray-700 text-gray-400 rounded">
                    未启用
                  </span>
                  <span class="text-xs text-gray-500">优先级: {{ client.priority }}</span>
                </div>
              </div>
              <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" :checked="client.is_active"
                       @change="toggleClientActive(client)"
                       class="sr-only peer">
                <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer
                            peer-checked:after:translate-x-full peer-checked:after:border-white
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                            after:bg-white after:border-gray-300 after:border after:rounded-full
                            after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600">
                </div>
              </label>
            </div>

            <!-- Client Details -->
            <div class="space-y-2 mb-3 text-sm">
              <div class="flex justify-between">
                <span class="text-gray-400">MT5 登录:</span>
                <span class="font-mono">{{ client.mt5_login }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400">服务器:</span>
                <span class="font-mono text-xs">{{ client.mt5_server }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400">密码类型:</span>
                <span>{{ client.password_type === 'primary' ? '主密码' : '只读密码' }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400">MT5 路径:</span>
                <span class="font-mono text-xs truncate max-w-[200px]" :title="client.mt5_path">
                  {{ client.mt5_path }}
                </span>
              </div>
              <div v-if="client.proxy_id" class="flex justify-between">
                <span class="text-gray-400">代理:</span>
                <span class="text-xs">ID: {{ client.proxy_id }}</span>
              </div>
              <div v-else class="flex justify-between">
                <span class="text-gray-400">代理:</span>
                <span class="text-gray-500">直连</span>
              </div>
            </div>

            <!-- Connection Stats -->
            <div v-if="client.total_connections > 0" class="bg-gray-800 p-2 rounded mb-3 text-xs">
              <div class="flex justify-between mb-1">
                <span class="text-gray-400">连接统计:</span>
                <span>{{ client.total_connections }} 次</span>
              </div>
              <div class="flex justify-between mb-1">
                <span class="text-gray-400">失败次数:</span>
                <span :class="client.failed_connections > 0 ? 'text-red-400' : ''">
                  {{ client.failed_connections }} 次
                </span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400">平均延迟:</span>
                <span>{{ client.avg_latency_ms?.toFixed(0) || 0 }} ms</span>
              </div>
            </div>

            <!-- Action Buttons -->
            <div class="flex gap-2">
              <button v-if="client.connection_status !== 'connected'"
                      @click="connectClient(client)"
                      class="btn-primary flex-1 text-sm py-1.5">
                连接
              </button>
              <button v-else
                      @click="disconnectClient(client)"
                      class="bg-yellow-600 hover:bg-yellow-700 text-white px-3 py-1.5 rounded flex-1 text-sm">
                断开
              </button>
              <button @click="openEditClientModal(client)"
                      class="btn-secondary flex-1 text-sm py-1.5">
                编辑
              </button>
              <button @click="deleteClient(client)"
                      class="bg-red-600 hover:bg-red-700 text-white px-3 py-1.5 rounded flex-1 text-sm">
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add/Edit Client Modal -->
    <div v-if="showClientForm" class="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-[60] p-4">
      <div class="bg-gray-900 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div class="p-6">
          <h3 class="text-xl font-bold mb-4">{{ isEditMode ? '编辑客户端' : '新增客户端' }}</h3>

          <form @submit.prevent="saveClient" class="space-y-4">
            <!-- Client Name -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">客户端名称 *</label>
              <input type="text" v-model="clientForm.client_name" required
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                     placeholder="例如: 主客户端" />
            </div>

            <!-- MT5 Login -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">MT5 登录账号 *</label>
              <input type="text" v-model="clientForm.mt5_login" required
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono"
                     placeholder="输入MT5登录账号" />
            </div>

            <!-- MT5 Password -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">MT5 密码 *</label>
              <input type="password" v-model="clientForm.mt5_password"
                     :required="!isEditMode"
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono"
                     :placeholder="isEditMode ? '留空表示不修改' : '输入MT5密码'" />
            </div>

            <!-- Password Type -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">密码类型 *</label>
              <select v-model="clientForm.password_type" required
                      class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                <option value="primary">主密码</option>
                <option value="readonly">只读密码</option>
              </select>
            </div>

            <!-- MT5 Server -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">MT5 服务器 *</label>
              <input type="text" v-model="clientForm.mt5_server" required
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono"
                     placeholder="例如: BybitGlobal-Demo" />
            </div>

            <!-- MT5 Path -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">MT5 安装路径 *</label>
              <div class="flex gap-2">
                <input type="text" v-model="clientForm.mt5_path" required
                       class="flex-1 px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                       placeholder="C:\Program Files\MetaTrader 5\terminal64.exe" />
                <button type="button" @click="detectMT5Paths"
                        class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm whitespace-nowrap">
                  自动检测
                </button>
              </div>
            </div>

            <!-- MT5 Data Path (Optional) -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">MT5 数据路径 (可选)</label>
              <input type="text" v-model="clientForm.mt5_data_path"
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                     placeholder="留空使用默认路径" />
            </div>

            <!-- Proxy Selection -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">代理 (可选)</label>
              <select v-model="clientForm.proxy_id"
                      class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                <option :value="null">直连 (不使用代理)</option>
                <option v-for="proxy in availableProxies" :key="proxy.proxy_id" :value="proxy.proxy_id">
                  {{ proxy.proxy_ip }}:{{ proxy.proxy_port }} - {{ proxy.proxy_name }}
                </option>
              </select>
            </div>

            <!-- Priority -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">优先级 *</label>
              <input type="number" v-model.number="clientForm.priority" required min="1" max="100"
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                     placeholder="1-100, 数字越小优先级越高" />
              <p class="text-xs text-gray-500 mt-1">数字越小优先级越高，用于故障转移</p>
            </div>

            <!-- Active Toggle -->
            <div class="flex items-center gap-3">
              <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" v-model="clientForm.is_active" class="sr-only peer">
                <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer
                            peer-checked:after:translate-x-full peer-checked:after:border-white
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                            after:bg-white after:border-gray-300 after:border after:rounded-full
                            after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600">
                </div>
              </label>
              <span class="text-sm text-gray-400">启用此客户端</span>
            </div>

            <!-- Form Actions -->
            <div class="flex gap-3 pt-4">
              <button type="submit" class="btn-primary flex-1">
                {{ isEditMode ? '保存' : '创建' }}
              </button>
              <button type="button" @click="closeClientForm" class="btn-secondary flex-1">
                取消
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMT5ClientStore } from '@/stores/mt5Client'
import { useProxyStore } from '@/stores/proxy'

const props = defineProps({
  show: Boolean,
  account: Object
})

const emit = defineEmits(['close', 'updated'])

const mt5ClientStore = useMT5ClientStore()
const proxyStore = useProxyStore()

const loading = ref(false)
const showClientForm = ref(false)
const isEditMode = ref(false)
const currentClient = ref(null)

const clientForm = ref({
  client_name: '',
  mt5_login: '',
  mt5_password: '',
  password_type: 'primary',
  mt5_server: '',
  mt5_path: '',
  mt5_data_path: '',
  proxy_id: null,
  priority: 1,
  is_active: true
})

const clients = computed(() => {
  if (!props.account) return []
  return mt5ClientStore.getClientsByAccount(props.account.account_id)
})

const availableProxies = computed(() => proxyStore.proxies)

watch(() => props.show, async (newVal) => {
  if (newVal && props.account) {
    await loadClients()
    await proxyStore.fetchProxies()
  }
})

async function loadClients() {
  if (!props.account) return
  loading.value = true
  try {
    await mt5ClientStore.fetchClients(props.account.account_id)
  } catch (error) {
    console.error('Failed to load MT5 clients:', error)
  } finally {
    loading.value = false
  }
}

function openAddClientModal() {
  isEditMode.value = false
  currentClient.value = null
  clientForm.value = {
    client_name: '',
    mt5_login: '',
    mt5_password: '',
    password_type: 'primary',
    mt5_server: '',
    mt5_path: '',
    mt5_data_path: '',
    proxy_id: null,
    priority: 1,
    is_active: true
  }
  showClientForm.value = true
}

function openEditClientModal(client) {
  isEditMode.value = true
  currentClient.value = client
  clientForm.value = {
    client_name: client.client_name,
    mt5_login: client.mt5_login,
    mt5_password: '',
    password_type: client.password_type,
    mt5_server: client.mt5_server,
    mt5_path: client.mt5_path,
    mt5_data_path: client.mt5_data_path || '',
    proxy_id: client.proxy_id,
    priority: client.priority,
    is_active: client.is_active
  }
  showClientForm.value = true
}

function closeClientForm() {
  showClientForm.value = false
  isEditMode.value = false
  currentClient.value = null
}

async function saveClient() {
  try {
    const data = { ...clientForm.value }
    if (isEditMode.value && !data.mt5_password) {
      delete data.mt5_password
    }

    if (isEditMode.value) {
      await mt5ClientStore.updateClient(currentClient.value.client_id, data)
    } else {
      await mt5ClientStore.createClient(props.account.account_id, data)
    }

    closeClientForm()
    emit('updated')
  } catch (error) {
    alert(error.response?.data?.detail || '保存失败')
  }
}

async function toggleClientActive(client) {
  try {
    await mt5ClientStore.updateClient(client.client_id, {
      is_active: !client.is_active
    })
    emit('updated')
  } catch (error) {
    alert('切换状态失败')
  }
}

async function connectClient(client) {
  try {
    await mt5ClientStore.connectClient(client.client_id)
    emit('updated')
  } catch (error) {
    alert(error.response?.data?.detail || '连接失败')
  }
}

async function disconnectClient(client) {
  try {
    await mt5ClientStore.disconnectClient(client.client_id)
    emit('updated')
  } catch (error) {
    alert(error.response?.data?.detail || '断开失败')
  }
}

async function deleteClient(client) {
  if (!confirm(`确定要删除客户端 "${client.client_name}" 吗？`)) return

  try {
    await mt5ClientStore.deleteClient(client.client_id)
    emit('updated')
  } catch (error) {
    alert('删除失败')
  }
}

async function detectMT5Paths() {
  try {
    const paths = await mt5ClientStore.detectMT5Installations()
    if (paths && paths.length > 0) {
      clientForm.value.mt5_path = paths[0]
      alert(`检测到 ${paths.length} 个MT5安装路径，已自动填充第一个`)
    } else {
      alert('未检测到MT5安装路径')
    }
  } catch (error) {
    alert('检测失败')
  }
}

function getClientBorderClass(client) {
  if (client.connection_status === 'connected') return 'border-green-600'
  if (client.connection_status === 'connecting') return 'border-yellow-600'
  if (client.connection_status === 'error') return 'border-red-600'
  return 'border-gray-700'
}

function getStatusClass(status) {
  const classes = {
    connected: 'bg-green-900 text-green-300',
    connecting: 'bg-yellow-900 text-yellow-300',
    disconnected: 'bg-gray-700 text-gray-400',
    error: 'bg-red-900 text-red-300'
  }
  return classes[status] || classes.disconnected
}

function getStatusText(status) {
  const texts = {
    connected: '已连接',
    connecting: '连接中',
    disconnected: '未连接',
    error: '错误'
  }
  return texts[status] || '未知'
}

function close() {
  emit('close')
}
</script>

