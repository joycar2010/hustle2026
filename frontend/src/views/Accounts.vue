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
                默认
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
                <span class="font-mono text-xs">{{ maskString(account.api_secret) }}</span>
              </div>
            </div>
          </div>

          <!-- MT5 Info (Only for MT5 accounts) -->
          <div v-if="account.is_mt5_account" class="bg-gray-800 p-3 rounded">
            <div class="text-xs text-gray-400 mb-2">MT5 配置</div>
            <div class="text-sm">
              <div class="flex justify-between items-center mb-1">
                <span class="text-gray-500">MT5 ID:</span>
                <span class="font-mono text-xs">{{ account.mt5_id || 'N/A' }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-gray-500">Server:</span>
                <span class="font-mono text-xs">{{ account.mt5_server || 'N/A' }}</span>
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
          <button @click="openEditModal(account)" class="btn-secondary flex-1">
            编辑
          </button>
          <button @click="deleteAccount(account.account_id)" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded flex-1">
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
                  <input type="password" v-model="accountForm.api_secret" required
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         :placeholder="`输入 ${accountForm.platform_id === 1 ? 'Binance' : 'Bybit'} API Secret`" />
                </div>

                <div v-if="accountForm.platform_id === 2">
                  <label class="block text-sm text-gray-400 mb-2">Passphrase (可选)</label>
                  <input type="password" v-model="accountForm.passphrase"
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         placeholder="输入 Bybit API Passphrase (如果需要)" />
                </div>
              </div>
            </div>

            <!-- MT5 Section (Only for MT5 accounts) -->
            <div v-if="accountForm.platform_id === 2 && accountForm.is_mt5_account" class="border-t border-gray-700 pt-4">
              <h3 class="text-lg font-semibold mb-3">MT5 配置</h3>

              <div class="space-y-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-2">MT5 ID *</label>
                  <input type="text" v-model="accountForm.mt5_id" :required="accountForm.is_mt5_account"
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         placeholder="输入 MT5 账户 ID" />
                </div>

                <div>
                  <label class="block text-sm text-gray-400 mb-2">MT5 Password *</label>
                  <input type="password" v-model="accountForm.mt5_primary_pwd" :required="accountForm.is_mt5_account"
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         placeholder="输入 MT5 密码" />
                </div>

                <div>
                  <label class="block text-sm text-gray-400 mb-2">MT5 Server *</label>
                  <input type="text" v-model="accountForm.mt5_server" :required="accountForm.is_mt5_account"
                         class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary font-mono text-sm"
                         placeholder="例如: Bybit-Demo" />
                </div>
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
              <span class="text-sm text-gray-400">设为默认账户</span>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'

// Data
const accounts = ref([])
const showModal = ref(false)
const isEditMode = ref(false)
const accountForm = ref({
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
  is_active: true
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
    is_active: true
  }
  showModal.value = true
}

function openEditModal(account) {
  isEditMode.value = true
  accountForm.value = {
    account_id: account.account_id,
    account_name: account.account_name,
    platform_id: account.platform_id,
    api_key: account.api_key || '',
    api_secret: '', // Don't populate secret for security
    passphrase: '',
    mt5_id: account.mt5_id || '',
    mt5_primary_pwd: '', // Don't populate password for security
    mt5_server: account.mt5_server || '',
    is_mt5_account: account.is_mt5_account,
    is_default: account.is_default,
    is_active: account.is_active
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
      is_default: accountForm.value.is_default
    }

    // Add MT5 fields if it's an MT5 account
    if (accountForm.value.is_mt5_account) {
      data.mt5_id = accountForm.value.mt5_id
      data.mt5_primary_pwd = accountForm.value.mt5_primary_pwd
      data.mt5_server = accountForm.value.mt5_server
    }

    if (isEditMode.value) {
      // For edit mode, only send fields that are not empty
      const updateData = {
        account_name: accountForm.value.account_name,
        is_default: accountForm.value.is_default,
        is_active: accountForm.value.is_active
      }

      // Only include API credentials if they were changed (not empty)
      if (accountForm.value.api_key) {
        updateData.api_key = accountForm.value.api_key
      }
      if (accountForm.value.api_secret) {
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

function maskString(str) {
  if (!str) return 'N/A'
  if (str.length <= 8) return '****'
  return str.substring(0, 4) + '****' + str.substring(str.length - 4)
}
</script>
