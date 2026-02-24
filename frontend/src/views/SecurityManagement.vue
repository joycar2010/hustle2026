<template>
  <div class="security-management p-6">
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-2xl font-bold">安全组件管理</h1>
      <div class="flex gap-2">
        <span class="text-sm text-gray-600">
          已启用: <span class="font-semibold text-green-600">{{ enabledComponents.length }}</span> /
          总计: <span class="font-semibold">{{ components.length }}</span>
        </span>
      </div>
    </div>

    <div v-if="error" class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
      {{ error }}
    </div>

    <div v-if="loading" class="text-center py-8">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="component in components"
        :key="component.component_id"
        class="bg-white rounded-lg shadow hover:shadow-lg transition-shadow"
      >
        <div class="p-4">
          <div class="flex justify-between items-start mb-3">
            <div>
              <h3 class="text-lg font-semibold">{{ component.component_name }}</h3>
              <span
                :class="getTypeColor(component.component_type)"
                class="text-xs px-2 py-1 rounded mt-1 inline-block"
              >
                {{ getTypeLabel(component.component_type) }}
              </span>
            </div>
            <button
              @click="toggleComponent(component)"
              :class="component.is_enabled ? 'bg-green-500' : 'bg-gray-400'"
              class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            >
              <span
                :class="component.is_enabled ? 'translate-x-6' : 'translate-x-1'"
                class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              />
            </button>
          </div>

          <p class="text-sm text-gray-600 mb-3">{{ component.description }}</p>

          <div class="flex items-center justify-between text-xs text-gray-500 mb-3">
            <span>优先级: {{ component.priority }}</span>
            <span>版本: {{ component.version }}</span>
          </div>

          <div class="flex gap-2">
            <button
              @click="viewComponent(component)"
              class="flex-1 bg-blue-50 hover:bg-blue-100 text-blue-600 px-3 py-2 rounded text-sm"
            >
              查看详情
            </button>
            <button
              @click="configComponent(component)"
              class="flex-1 bg-gray-50 hover:bg-gray-100 text-gray-600 px-3 py-2 rounded text-sm"
            >
              配置
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 配置对话框 -->
    <div v-if="showConfigDialog" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto">
        <h3 class="text-lg font-semibold mb-4">配置 - {{ currentComponent?.component_name }}</h3>
        <div class="mb-4">
          <label class="block text-sm font-medium mb-2">配置 (JSON格式)</label>
          <textarea
            v-model="configJson"
            rows="15"
            class="w-full border rounded px-3 py-2 font-mono text-sm"
            placeholder='{"key": "value"}'
          ></textarea>
        </div>
        <div class="flex justify-end gap-2">
          <button
            @click="closeConfigDialog"
            class="px-4 py-2 border rounded hover:bg-gray-100"
          >
            取消
          </button>
          <button
            @click="saveConfig"
            class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            保存
          </button>
        </div>
      </div>
    </div>

    <!-- 详情对话框 -->
    <div v-if="showDetailDialog" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[80vh] overflow-y-auto">
        <h3 class="text-lg font-semibold mb-4">{{ currentComponent?.component_name }}</h3>

        <div class="space-y-4">
          <div>
            <label class="text-sm font-medium text-gray-600">组件代码</label>
            <p class="text-sm"><code class="bg-gray-100 px-2 py-1 rounded">{{ currentComponent?.component_code }}</code></p>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-600">描述</label>
            <p class="text-sm">{{ currentComponent?.description }}</p>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-600">类型</label>
            <p class="text-sm">{{ getTypeLabel(currentComponent?.component_type) }}</p>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-600">状态</label>
            <p class="text-sm">
              <span :class="currentComponent?.is_enabled ? 'text-green-600' : 'text-gray-600'">
                {{ currentComponent?.is_enabled ? '已启用' : '已禁用' }}
              </span>
            </p>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-600">配置</label>
            <pre class="text-xs bg-gray-50 p-3 rounded overflow-x-auto">{{ JSON.stringify(currentComponent?.config, null, 2) }}</pre>
          </div>
          <div>
            <label class="text-sm font-medium text-gray-600">最后更新</label>
            <p class="text-sm">{{ formatDate(currentComponent?.updated_at) }}</p>
          </div>
        </div>

        <div class="flex justify-end gap-2 mt-6">
          <button
            @click="viewLogs"
            class="px-4 py-2 border rounded hover:bg-gray-100"
          >
            查看日志
          </button>
          <button
            @click="closeDetailDialog"
            class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSecurityStore } from '@/stores/security'
import { storeToRefs } from 'pinia'

const securityStore = useSecurityStore()
const { components, loading, error, enabledComponents } = storeToRefs(securityStore)

const showConfigDialog = ref(false)
const showDetailDialog = ref(false)
const currentComponent = ref(null)
const configJson = ref('')

onMounted(async () => {
  await securityStore.fetchComponents()
})

const getTypeColor = (type) => {
  const colors = {
    middleware: 'bg-blue-100 text-blue-800',
    service: 'bg-green-100 text-green-800',
    protection: 'bg-purple-100 text-purple-800'
  }
  return colors[type] || 'bg-gray-100 text-gray-800'
}

const getTypeLabel = (type) => {
  const labels = {
    middleware: '中间件',
    service: '服务',
    protection: '防护'
  }
  return labels[type] || type
}

const toggleComponent = async (component) => {
  try {
    if (component.is_enabled) {
      await securityStore.disableComponent(component.component_id)
    } else {
      await securityStore.enableComponent(component.component_id)
    }
  } catch (err) {
    alert('操作失败')
  }
}

const viewComponent = async (component) => {
  currentComponent.value = component
  showDetailDialog.value = true
}

const configComponent = (component) => {
  currentComponent.value = component
  configJson.value = JSON.stringify(component.config || {}, null, 2)
  showConfigDialog.value = true
}

const saveConfig = async () => {
  try {
    const config = JSON.parse(configJson.value)
    await securityStore.updateComponentConfig(currentComponent.value.component_id, config)
    alert('配置保存成功')
    closeConfigDialog()
  } catch (err) {
    alert('配置格式错误或保存失败')
  }
}

const closeConfigDialog = () => {
  showConfigDialog.value = false
  currentComponent.value = null
  configJson.value = ''
}

const closeDetailDialog = () => {
  showDetailDialog.value = false
  currentComponent.value = null
}

const viewLogs = async () => {
  // Navigate to logs page
  console.log('View logs for:', currentComponent.value)
}

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}
</script>
