<template>
  <div class="container mx-auto px-4 py-6">
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-3xl font-bold">账户管理</h1>
      <button @click="openAddModal" class="btn-primary">
        + 新增账户
      </button>
    </div>

    <!-- Accounts Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
      <div v-for="account in accounts" :key="account.account_id"
           class="card"
           :class="{ 'opacity-60 border-gray-700': !account.is_active }">
        <!-- Account Header -->
        <div class="flex justify-between items-start mb-4">
          <div>
            <h3 class="text-xl font-bold mb-1">{{ account.account_name }}</h3>
            <div class="flex items-center gap-2">
              <span class="text-sm text-gray-400">ID: {{ account.account_id }}</span>
              <span class="px-2 py-1 bg-blue-900 text-blue-300 rounded text-xs">
                {{ getPlatformName(account.platform_id, account.is_mt5_account) }}
              </span>
              <span v-if="account.is_default" class="px-2 py-1 bg-yellow-900 text-yellow-300 rounded text-xs">
                {{ account.platform_id === 1 ? 'Binance默认' : 'Bybit MT5默认' }}
              </span>
              <span v-if="!account.is_active" class="px-2 py-1 bg-gray-700 text-gray-400 rounded text-xs">
                未启用
              </span>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <!-- Enable/Disable Toggle -->
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" :checked="account.is_active"
                     @change="toggleAccountStatus(account.account_id, !account.is_active)"
                     class="sr-only peer">
              <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer
                          peer-checked:after:translate-x-full peer-checked:after:border-white
                          after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                          after:bg-white after:border-gray-300 after:border after:rounded-full
                          after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600">
              </div>
            </label>
            <span :class="account.is_active ? 'text-green-500' : 'text-gray-500'" class="text-xs">
              {{ account.is_active ? '启用' : '禁用' }}
            </span>
          </div>
        </div>

        <!-- Account Details -->
        <div class="space-y-3 mb-4">
          <!-- API Info -->
          <div class="bg-gray-800 p-3 rounded">
            <div class="text-xs text-gray-400 mb-2">
              {{ getPlatformName(account.platform_id, account.is_mt5_account) }} API
            </div>
            <div class="text-sm">
              <div class="flex justify-between items-center mb-1">
                <span class="text-gray-500">API Key:</span>
                <span class="font-mono text-xs">{{ maskString(account.api_key) }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-gray-500">API Secret:</span>
                <span class="font-mono text-xs">{{ maskSecret(account.api_secret) }}</span>
              </div>
            </div>
          </div>

          <!-- Account Metadata -->
          <div class="bg-gray-800 p-3 rounded">
            <div class="text-xs text-gray-400 mb-2">账户信息</div>
            <div class="text-sm">
              <div class="flex justify-between items-center mb-1">
                <span class="text-gray-500">创建时间:</span>
                <span class="text-xs">{{ formatDate(account.create_time) }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-gray-500">更新时间:</span>
                <span class="text-xs">{{ formatDate(account.update_time) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Action Buttons -->
        <div class="flex gap-2">
          <button @click="openProxyConfig(account)" class="btn-secondary flex-1" title="配置代理">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
            </svg>
            代理
          </button>
          <button @click="openEditModal(account)" class="btn-secondary flex-1 whitespace-nowrap">
            编辑
          </button>
          <button @click="deleteAccount(account.account_id)" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded flex-1 whitespace-nowrap">
            删除
          </button>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="accounts.length === 0" class="col-span-full text-center py-12">
        <div class="text-gray-500 mb-4">暂无账户</div>
        <button @click="openAddModal" class="btn-primary">
          + 新增第一个账户
        </button>
      </div>
    </div>

    <!-- Add/Edit Modal -->
    <div v-if="showModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div class="p-6">
          <h2 class="text-2xl font-bold mb-6">{{ isEditMode ? '编辑账户' : '新增账户' }}</h2>

          <form @submit.prevent="saveAccount" class="space-y-4">
            <!-- Account Name -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">账户名称 *</label>
              <input type="text" v-model="accountForm.account_name" required
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                     placeholder="例如: 主账户" />
            </div>

            <!-- Platform Type -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">平台类别 *</label>
              <select v-model="accountForm.platform_id" required
                      @change="onPlatformChange"
                      class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                <option :value="1">Binance</option>
                <option :value="2">Bybit</option>
              </select>
            </div>

            <!-- MT5 Account Toggle (Only for Bybit) -->
            <div v-if="accountForm.platform_id === 2" class="flex items-center gap-3">
              <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" v-model="accountForm.is_mt5_account" class="sr-only peer">
                <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer
                            peer-checked:after:translate-x-full peer-checked:after:border-white
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                            after:bg-white after:border-gray-300 after:border after:rounded-full
                            after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600">
                </div>
              </label>
              <span class="text-sm text-gray-400">这是 MT5 账户</span>
              <span v-if="accountForm.is_mt5_account" class="text-xs text-yellow-400">
                (MT5配置请在系统管理 > MT5客户端管理中设置)
              </span>
            </div>

            <!-- API Configuration Section -->
            <div class="border-t border-gray-700 pt-4">
              <h3 class="text-lg font-semibold mb-3">
                {{ accountForm.platform_id === 1 ? 'Binance' : 'Bybit' }} API 配置
              </h3>

              <div class="space-y-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-2">API Key *</label>
                  <input type="text" v-model="accountForm.api_key" required
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         :placeholder="`输入 ${accountForm.platform_id === 1 ? 'Binance' : 'Bybit'} API Key`" />
                </div>

                <div>
                  <label class="block text-sm text-gray-400 mb-2">API Secret *</label>
                  <div class="flex gap-2">
                    <input :type="showApiSecret ? 'text' : 'password'"
                           v-model="accountForm.api_secret"
                           :required="!isEditMode"
                           class="flex-1 px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                           :placeholder="isEditMode ? '留空表示不修改' : `输入 ${accountForm.platform_id === 1 ? 'Binance' : 'Bybit'} API Secret`" />
                    <button v-if="isEditMode"
                            type="button"
                            @click="requestViewSecret"
                            class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm whitespace-nowrap">
                      查看密钥
                    </button>
                  </div>
                </div>

                <div v-if="accountForm.platform_id === 2">
                  <label class="block text-sm text-gray-400 mb-2">Passphrase (可选)</label>
                  <input type="password" v-model="accountForm.passphrase"
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         placeholder="输入 Bybit API Passphrase (如果需要)" />
                </div>
              </div>
            </div>

            <!-- Leverage Setting -->
            <div class="border-t border-gray-700 pt-4">
              <label class="block text-sm text-gray-400 mb-2">杠杆倍数</label>
              <input type="number" v-model.number="accountForm.leverage" min="1" max="500"
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                     :placeholder="accountForm.platform_id === 1 ? '默认: 20x' : '默认: 100x'" />
              <div class="text-xs text-gray-500 mt-1">
                {{ accountForm.platform_id === 1 ? 'Binance 推荐杠杆: 20x' : 'Bybit 推荐杠杆: 100x' }}
              </div>
            </div>

            <!-- Default Account Toggle -->
            <div class="border-t border-gray-700 pt-4 flex items-center gap-3">
              <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" v-model="accountForm.is_default" class="sr-only peer">
                <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer
                            peer-checked:after:translate-x-full peer-checked:after:border-white
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                            after:bg-white after:border-gray-300 after:border after:rounded-full
                            after:h-5 after:w-5 after:transition-all peer-checked:bg-yellow-600">
                </div>
              </label>
              <span class="text-sm text-gray-400">设为{{ accountForm.platform_id === 1 ? 'Binance' : 'Bybit MT5' }}默认账户</span>
            </div>

            <!-- Form Actions -->
            <div class="flex gap-3 pt-4">
              <button type="submit" class="btn-primary flex-1">
                {{ isEditMode ? '保存修改' : '创建账户' }}
              </button>
              <button type="button" @click="closeModal" class="btn-secondary flex-1">
                取消
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Password Verification Modal -->
    <div v-if="showPasswordModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 rounded-lg max-w-md w-full">
        <div class="p-6">
          <h2 class="text-xl font-bold mb-4">验证用户密码</h2>
          <p class="text-sm text-gray-400 mb-4">为了安全，查看API密钥需要验证您的登录密码</p>

          <form @submit.prevent="verifyPasswordAndViewSecret" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-2">登录密码</label>
              <input type="password"
                     v-model="verificationPassword"
                     required
                     autofocus
                     class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                     placeholder="输入您的登录密码" />
            </div>

            <div v-if="passwordError" class="text-red-500 text-sm">
              {{ passwordError }}
            </div>

            <div class="flex gap-3">
              <button type="submit" class="btn-primary flex-1">
                验证并查看
              </button>
              <button type="button" @click="closePasswordModal" class="btn-secondary flex-1">
                取消
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Proxy Configuration Modal -->
    <div v-if="showProxyModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 rounded-lg max-w-md w-full">
        <div class="p-6">
          <h2 class="text-2xl font-bold mb-6">代理配置 - {{ currentAccount?.account_name }}</h2>

          <div class="space-y-4">
            <!-- Platform Selection -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">平台</label>
              <select v-model="proxyConfigForm.platform_id"
                      class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                <option :value="1">Binance</option>
                <option :value="2">Bybit</option>
              </select>
            </div>

            <!-- Proxy Selection -->
            <div>
              <label class="block text-sm text-gray-400 mb-2">代理</label>
              <select v-model="proxyConfigForm.proxy_id"
                      class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary">
                <option :value="null">直连（不使用代理）</option>
                <option v-for="proxy in proxyStore.activeProxies" :key="proxy.id" :value="proxy.id">
                  {{ proxy.provider === 'local' ? '本地' : proxy.provider === 'qingguo' ? '青果' : '自定义' }} -
                  {{ proxy.host }}:{{ proxy.port }}
                  (健康度: {{ proxy.health_score }})
                </option>
              </select>
            </div>

            <!-- Current Proxy Info -->
            <div v-if="currentProxyBinding" class="bg-dark-200 p-3 rounded">
              <div class="text-xs text-gray-400 mb-2">当前代理</div>
              <div class="text-sm">
                <div class="flex justify-between items-center mb-1">
                  <span class="text-gray-500">地址:</span>
                  <span class="font-mono text-xs">{{ currentProxyBinding.host }}:{{ currentProxyBinding.port }}</span>
                </div>
                <div class="flex justify-between items-center">
                  <span class="text-gray-500">健康度:</span>
                  <span class="text-xs">{{ currentProxyBinding.health_score }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="flex gap-3 mt-6">
            <button @click="saveProxyConfig" class="btn-primary flex-1">
              保存
            </button>
            <button @click="unbindProxy" class="btn-secondary flex-1">
              解绑
            </button>
            <button @click="closeProxyModal" class="btn-secondary flex-1">
              取消
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { useProxyStore } from '@/stores/proxy'
import { useNotificationStore } from '@/stores/notification'

const proxyStore = useProxyStore()
const notificationStore = useNotificationStore()

// Data
const accounts = ref([])
const showModal = ref(false)
const isEditMode = ref(false)
const showPasswordModal = ref(false)
const showApiSecret = ref(false)
const showMt5Password = ref(false)
const viewingSecretType = ref('') // 'api' or 'mt5'
const verificationPassword = ref('')
const passwordError = ref('')
const showProxyModal = ref(false)
const currentAccount = ref(null)
const currentProxyBinding = ref(null)
const proxyConfigForm = ref({
  platform_id: 1,
  proxy_id: null
})
const accountForm = ref({
  account_id: null,
  account_name: '',
  platform_id: 2,
  api_key: '',
  api_secret: '',
  passphrase: '',
  is_mt5_account: false,
  is_default: false,
  is_active: true,
  leverage: 100  // Default leverage: Binance 20x, Bybit 100x
})

// Initialize
onMounted(() => {
  fetchAccounts()
})

// Functions
async function fetchAccounts() {
  try {
    const response = await api.get('/api/v1/accounts')
    accounts.value = response.data
  } catch (error) {
    console.error('Failed to fetch accounts:', error)
    alert('获取账户列表失败: ' + (error.response?.data?.detail || error.message))
    accounts.value = []
  }
}

function getPlatformName(platformId, isMt5Account) {
  if (platformId === 1) return 'Binance'
  if (platformId === 2) {
    return isMt5Account ? 'Bybit MT5' : 'Bybit'
  }
  return 'Unknown'
}

function formatDate(dateString) {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function openAddModal() {
  isEditMode.value = false
  accountForm.value = {
    account_id: null,
    account_name: '',
    platform_id: 2,
    api_key: '',
    api_secret: '',
    passphrase: '',
    mt5_id: '',
    mt5_primary_pwd: '',
    mt5_server: '',
    is_mt5_account: false,
    is_default: false,
    is_active: true,
    leverage: 100  // Default: Bybit 100x
  }
  showModal.value = true
}

function openEditModal(account) {
  isEditMode.value = true
  showApiSecret.value = false
  showMt5Password.value = false
  accountForm.value = {
    account_id: account.account_id,
    account_name: account.account_name,
    platform_id: account.platform_id,
    api_key: account.api_key || '',
    api_secret: '********', // Show masked secret
    passphrase: '',
    is_mt5_account: account.is_mt5_account,
    is_default: account.is_default,
    is_active: account.is_active,
    leverage: account.leverage || (account.platform_id === 1 ? 20 : 100)
  }
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

function onPlatformChange() {
  // Reset MT5 fields when platform changes
  if (accountForm.value.platform_id === 1) {
    accountForm.value.is_mt5_account = false
    accountForm.value.mt5_id = ''
    accountForm.value.mt5_primary_pwd = ''
    accountForm.value.mt5_server = ''
    accountForm.value.leverage = 20  // Binance default 20x
  } else {
    accountForm.value.leverage = 100  // Bybit default 100x
  }
}

async function saveAccount() {
  try {
    // Prepare data for API
    const data = {
      account_name: accountForm.value.account_name,
      platform_id: accountForm.value.platform_id,
      api_key: accountForm.value.api_key,
      api_secret: accountForm.value.api_secret,
      passphrase: accountForm.value.passphrase || null,
      is_mt5_account: accountForm.value.is_mt5_account,
      is_default: accountForm.value.is_default,
      leverage: accountForm.value.leverage || (accountForm.value.platform_id === 1 ? 20 : 100)
    }

    if (isEditMode.value) {
      // For edit mode, only send fields that are not empty
      const updateData = {
        account_name: accountForm.value.account_name,
        is_default: accountForm.value.is_default,
        is_active: accountForm.value.is_active,
        is_mt5_account: accountForm.value.is_mt5_account,
        leverage: accountForm.value.leverage
      }

      // Only include API credentials if they were changed (not empty and not masked)
      if (accountForm.value.api_key) {
        updateData.api_key = accountForm.value.api_key
      }
      if (accountForm.value.api_secret && accountForm.value.api_secret !== '********') {
        updateData.api_secret = accountForm.value.api_secret
      }
      if (accountForm.value.passphrase) {
        updateData.passphrase = accountForm.value.passphrase
      }

      await api.put(`/api/v1/accounts/${accountForm.value.account_id}`, updateData)
      alert('账户更新成功')
    } else {
      await api.post('/api/v1/accounts', data)
      alert('账户创建成功')
    }

    closeModal()
    await fetchAccounts()
  } catch (error) {
    console.error('Failed to save account:', error)
    alert('保存失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function toggleAccountStatus(accountId, newStatus) {
  try {
    await api.put(`/api/v1/accounts/${accountId}`, { is_active: newStatus })
    // Refresh accounts list to remove disabled accounts from display
    await fetchAccounts()
  } catch (error) {
    console.error('Failed to toggle account status:', error)
    alert('状态切换失败: ' + (error.response?.data?.detail || error.message))
    // Refresh to get correct state
    await fetchAccounts()
  }
}

async function deleteAccount(accountId) {
  // Find the account to check its status
  const account = accounts.value.find(a => a.account_id === accountId)

  if (!account) {
    alert('账户不存在')
    return
  }

  // Check if account is enabled
  if (account.is_active) {
    alert('此账号已启用，请禁用账户后再尝试操作！')
    return
  }

  // Check if account is default
  if (account.is_default) {
    alert('此账号已设置为默认账户，请取消默认设置后再尝试操作！')
    return
  }

  if (!confirm('确定要删除此账户吗？此操作不可恢复！')) {
    return
  }

  try {
    await api.delete(`/api/v1/accounts/${accountId}`)
    alert('账户已删除')
    await fetchAccounts()
  } catch (error) {
    console.error('Failed to delete account:', error)
    alert('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

// Proxy Configuration Functions
async function openProxyConfig(account) {
  currentAccount.value = account
  proxyConfigForm.value.platform_id = account.platform_id
  showProxyModal.value = true

  // Load proxies if not already loaded
  if (proxyStore.proxies.length === 0) {
    await proxyStore.fetchProxies()
  }

  // Load current proxy binding
  try {
    const binding = await proxyStore.getAccountProxy(account.account_id, account.platform_id)
    if (binding && binding.proxy_id) {
      currentProxyBinding.value = binding
      proxyConfigForm.value.proxy_id = binding.proxy_id
    } else {
      currentProxyBinding.value = null
      proxyConfigForm.value.proxy_id = null
    }
  } catch (error) {
    console.error('Failed to load proxy binding:', error)
    currentProxyBinding.value = null
    proxyConfigForm.value.proxy_id = null
  }
}

async function saveProxyConfig() {
  try {
    if (proxyConfigForm.value.proxy_id) {
      await proxyStore.bindProxyToAccount(
        currentAccount.value.account_id,
        proxyConfigForm.value.platform_id,
        proxyConfigForm.value.proxy_id
      )
      notificationStore.addNotification('success', '代理配置已保存')
    } else {
      await proxyStore.unbindProxyFromAccount(
        currentAccount.value.account_id,
        proxyConfigForm.value.platform_id
      )
      notificationStore.addNotification('success', '代理已解绑')
    }
    closeProxyModal()
  } catch (error) {
    console.error('Failed to save proxy config:', error)
    notificationStore.addNotification('error', '保存代理配置失败')
  }
}

async function unbindProxy() {
  if (!confirm('确定要解绑此账户的代理吗？')) return

  try {
    await proxyStore.unbindProxyFromAccount(
      currentAccount.value.account_id,
      proxyConfigForm.value.platform_id
    )
    notificationStore.addNotification('success', '代理已解绑')
    closeProxyModal()
  } catch (error) {
    console.error('Failed to unbind proxy:', error)
    notificationStore.addNotification('error', '解绑代理失败')
  }
}

function closeProxyModal() {
  showProxyModal.value = false
  currentAccount.value = null
  currentProxyBinding.value = null
  proxyConfigForm.value = {
    platform_id: 1,
    proxy_id: null
  }
}

function requestViewSecret() {
  viewingSecretType.value = 'api'
  showPasswordModal.value = true
  verificationPassword.value = ''
  passwordError.value = ''
}

function requestViewMt5Password() {
  viewingSecretType.value = 'mt5'
  showPasswordModal.value = true
  verificationPassword.value = ''
  passwordError.value = ''
}

function closePasswordModal() {
  showPasswordModal.value = false
  verificationPassword.value = ''
  passwordError.value = ''
  viewingSecretType.value = ''
}

async function verifyPasswordAndViewSecret() {
  try {
    passwordError.value = ''

    // Call backend API to verify password
    const response = await api.post('/api/v1/auth/verify-password', {
      password: verificationPassword.value
    })

    if (response.data.valid) {
      if (viewingSecretType.value === 'api') {
        // Fetch the actual API secret
        const secretResponse = await api.get(`/api/v1/accounts/${accountForm.value.account_id}/secret`)
        accountForm.value.api_secret = secretResponse.data.api_secret
        showApiSecret.value = true
      } else if (viewingSecretType.value === 'mt5') {
        // Fetch the actual MT5 password
        const secretResponse = await api.get(`/api/v1/accounts/${accountForm.value.account_id}/secret`)
        accountForm.value.mt5_primary_pwd = secretResponse.data.mt5_primary_pwd || ''
        showMt5Password.value = true
      }
      closePasswordModal()
    } else {
      passwordError.value = '密码错误，请重试'
    }
  } catch (error) {
    console.error('Failed to verify password:', error)
    passwordError.value = error.response?.data?.detail || '验证失败，请重试'
  }
}

function maskSecret(str) {
  if (!str) return 'N/A'
  // Return all asterisks for secrets
  return '****************************************'.substring(0, Math.max(str.length, 16))
}

function maskString(str) {
  if (!str) return 'N/A'
  if (str.length <= 8) return '****'
  return str.substring(0, 4) + '****' + str.substring(str.length - 4)
}
</script>
