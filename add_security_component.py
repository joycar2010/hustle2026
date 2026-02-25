#!/usr/bin/env python3
"""
Script to add Security Component management to System.vue
"""

def add_security_component_management():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add security tab in tabs array
    content = content.replace(
        "  { id: 'ssl', label: 'SSL证书管理' },",
        "  { id: 'ssl', label: 'SSL证书管理' },\n  { id: 'security', label: '安全组件管理' },"
    )

    # Add security component tab content before refresh tab
    security_tab_content = '''
      <!-- 安全组件管理 Tab -->
      <div v-if="activeTab === 'security'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">安全组件管理</h2>
            <button @click="loadSecurityComponents" class="btn-secondary">
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              刷新
            </button>
          </div>

          <!-- Component Type Filters -->
          <div class="flex space-x-2 mb-4">
            <button
              v-for="type in componentTypes"
              :key="type.value"
              @click="filterComponentType = type.value"
              :class="[
                'px-4 py-2 rounded text-sm font-medium transition-colors',
                filterComponentType === type.value
                  ? 'bg-primary text-white'
                  : 'bg-dark-200 text-text-secondary hover:bg-dark-300'
              ]"
            >
              {{ type.label }}
            </button>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">组件名称</th>
                  <th class="text-left py-3 px-4">组件代码</th>
                  <th class="text-left py-3 px-4">类型</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">优先级</th>
                  <th class="text-left py-3 px-4">最后检查</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="component in filteredComponents" :key="component.component_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">
                    <div class="font-medium">{{ component.component_name }}</div>
                    <div class="text-xs text-text-secondary">{{ component.description }}</div>
                  </td>
                  <td class="py-3 px-4 font-mono text-sm">{{ component.component_code }}</td>
                  <td class="py-3 px-4">
                    <span class="px-2 py-1 rounded text-xs" :class="getComponentTypeClass(component.component_type)">
                      {{ getComponentTypeLabel(component.component_type) }}
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <div class="flex items-center space-x-2">
                      <span :class="component.is_enabled ? 'text-success' : 'text-text-secondary'">
                        {{ component.is_enabled ? '已启用' : '已禁用' }}
                      </span>
                      <span v-if="component.status === 'error'" class="text-danger text-xs">(错误)</span>
                    </div>
                  </td>
                  <td class="py-3 px-4">{{ component.priority }}</td>
                  <td class="py-3 px-4 text-text-secondary text-sm">
                    {{ component.last_check_at ? formatDate(component.last_check_at) : '-' }}
                  </td>
                  <td class="py-3 px-4">
                    <button
                      v-if="!component.is_enabled"
                      @click="enableComponent(component)"
                      class="text-success hover:text-green-400 mr-2"
                    >
                      启用
                    </button>
                    <button
                      v-if="component.is_enabled"
                      @click="disableComponent(component)"
                      class="text-warning hover:text-yellow-400 mr-2"
                    >
                      禁用
                    </button>
                    <button @click="configureComponent(component)" class="text-primary hover:text-blue-400 mr-2">
                      配置
                    </button>
                    <button @click="viewComponentLogs(component)" class="text-text-secondary hover:text-text-primary">
                      日志
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="filteredComponents.length === 0" class="text-center py-8 text-text-secondary">
              暂无安全组件数据
            </div>
          </div>
        </div>

        <!-- Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">总组件数</div>
            <div class="text-2xl font-bold">{{ securityComponents.length }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">已启用</div>
            <div class="text-2xl font-bold text-success">{{ enabledComponentsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">已禁用</div>
            <div class="text-2xl font-bold text-text-secondary">{{ disabledComponentsCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">错误状态</div>
            <div class="text-2xl font-bold text-danger">{{ errorComponentsCount }}</div>
          </div>
        </div>
      </div>
'''

    # Insert before refresh tab
    content = content.replace(
        "      <div v-if=\"activeTab === 'refresh'\" class=\"space-y-6\">",
        security_tab_content + "\n      <div v-if=\"activeTab === 'refresh'\" class=\"space-y-6\">"
    )

    # Add state variables
    security_state = '''
// Security Component state
const securityComponents = ref([])
const filterComponentType = ref('all')
const showConfigModal = ref(false)
const showLogsModal = ref(false)
const currentComponent = ref(null)
const componentConfig = ref({})
const componentLogs = ref([])

const componentTypes = [
  { value: 'all', label: '全部' },
  { value: 'middleware', label: '中间件' },
  { value: 'service', label: '服务' },
  { value: 'protection', label: '防护' }
]

const filteredComponents = computed(() => {
  if (filterComponentType.value === 'all') {
    return securityComponents.value
  }
  return securityComponents.value.filter(c => c.component_type === filterComponentType.value)
})

const enabledComponentsCount = computed(() =>
  securityComponents.value.filter(c => c.is_enabled).length
)

const disabledComponentsCount = computed(() =>
  securityComponents.value.filter(c => !c.is_enabled).length
)

const errorComponentsCount = computed(() =>
  securityComponents.value.filter(c => c.status === 'error').length
)

'''

    # Insert after permission management state
    content = content.replace(
        "const apiPermissions = computed(() =>\n  allPermissions.value.filter(p => p.resource_type === 'api')\n)\nconst menuPermissions = computed(() =>\n  allPermissions.value.filter(p => p.resource_type === 'menu')\n)\nconst buttonPermissions = computed(() =>\n  allPermissions.value.filter(p => p.resource_type === 'button')\n)\n\n",
        "const apiPermissions = computed(() =>\n  allPermissions.value.filter(p => p.resource_type === 'api')\n)\nconst menuPermissions = computed(() =>\n  allPermissions.value.filter(p => p.resource_type === 'menu')\n)\nconst buttonPermissions = computed(() =>\n  allPermissions.value.filter(p => p.resource_type === 'button')\n)\n\n" + security_state
    )

    # Add functions
    security_functions = '''
// Security Component Functions
async function loadSecurityComponents() {
  try {
    const response = await api.get('/api/v1/security/components')
    securityComponents.value = response.data
  } catch (error) {
    console.error('Failed to load security components:', error)
    alert('加载安全组件失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function enableComponent(component) {
  if (!confirm(`确定要启用组件"${component.component_name}"吗？`)) return
  try {
    await api.post(`/api/v1/security/components/${component.component_id}/enable`, {
      reason: '手动启用'
    })
    alert('组件启用成功')
    await loadSecurityComponents()
  } catch (error) {
    console.error('Failed to enable component:', error)
    alert('启用组件失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function disableComponent(component) {
  if (!confirm(`确定要禁用组件"${component.component_name}"吗？`)) return
  try {
    await api.post(`/api/v1/security/components/${component.component_id}/disable`, {
      reason: '手动禁用'
    })
    alert('组件禁用成功')
    await loadSecurityComponents()
  } catch (error) {
    console.error('Failed to disable component:', error)
    alert('禁用组件失败: ' + (error.response?.data?.detail || error.message))
  }
}

function configureComponent(component) {
  currentComponent.value = component
  componentConfig.value = component.config_json || {}
  showConfigModal.value = true
}

async function saveComponentConfig() {
  try {
    await api.put(`/api/v1/security/components/${currentComponent.value.component_id}/config`, {
      config_json: componentConfig.value
    })
    alert('配置保存成功')
    showConfigModal.value = false
    await loadSecurityComponents()
  } catch (error) {
    console.error('Failed to save config:', error)
    alert('保存配置失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function viewComponentLogs(component) {
  try {
    currentComponent.value = component
    const response = await api.get(`/api/v1/security/components/${component.component_id}/logs`)
    componentLogs.value = response.data
    showLogsModal.value = true
  } catch (error) {
    console.error('Failed to load logs:', error)
    alert('加载日志失败: ' + (error.response?.data?.detail || error.message))
  }
}

function getComponentTypeLabel(type) {
  const labels = {
    'middleware': '中间件',
    'service': '服务',
    'protection': '防护'
  }
  return labels[type] || type
}

function getComponentTypeClass(type) {
  const classes = {
    'middleware': 'bg-primary text-white',
    'service': 'bg-success text-white',
    'protection': 'bg-warning text-dark-100'
  }
  return classes[type] || 'bg-dark-300 text-text-secondary'
}

'''

    # Insert before Permission Management Functions
    content = content.replace(
        '\n// Permission Management Functions',
        '\n' + security_functions + '// Permission Management Functions'
    )

    # Add to onMounted
    content = content.replace(
        'onMounted(async () => {\n  loadRoles()\n  loadCertificates()\n  loadAllPermissions()',
        'onMounted(async () => {\n  loadRoles()\n  loadCertificates()\n  loadAllPermissions()\n  loadSecurityComponents()'
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added security component management to {file_path}")

if __name__ == '__main__':
    add_security_component_management()
