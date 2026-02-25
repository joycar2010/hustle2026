#!/usr/bin/env python3
"""
Script to add RBAC and SSL Certificate management to System.vue
"""

def add_management_features():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the tabs array and add new tabs
    tabs_insert = """  { id: 'rbac', label: 'RBAC权限管理' },
  { id: 'ssl', label: 'SSL证书管理' },"""

    # Insert after 'alerts' tab
    content = content.replace(
        "  { id: 'alerts', label: '提醒声音设置' },",
        "  { id: 'alerts', label: '提醒声音设置' },\n" + tabs_insert
    )

    # Find where to insert the new tab content (after alerts tab, before refresh tab)
    rbac_tab_content = """
      <!-- RBAC权限管理 Tab -->
      <div v-if="activeTab === 'rbac'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">角色权限管理</h2>
            <div class="flex space-x-3">
              <button @click="openAddRoleModal" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                </svg>
                添加角色
              </button>
              <button @click="loadRoles" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">角色名称</th>
                  <th class="text-left py-3 px-4">角色代码</th>
                  <th class="text-left py-3 px-4">描述</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">创建时间</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="role in roles" :key="role.role_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">{{ role.role_name }}</td>
                  <td class="py-3 px-4 font-mono text-sm">{{ role.role_code }}</td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ role.description || '-' }}</td>
                  <td class="py-3 px-4">
                    <span :class="role.is_active ? 'text-success' : 'text-danger'">
                      {{ role.is_active ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ formatDate(role.created_at) }}</td>
                  <td class="py-3 px-4">
                    <button @click="editRole(role)" class="text-primary hover:text-blue-400 mr-2">编辑</button>
                    <button v-if="!role.is_system" @click="deleteRole(role.role_id)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="roles.length === 0" class="text-center py-8 text-text-secondary">
              暂无角色数据
            </div>
          </div>
        </div>
      </div>

      <!-- SSL证书管理 Tab -->
      <div v-if="activeTab === 'ssl'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">SSL证书管理</h2>
            <div class="flex space-x-3">
              <button @click="openUploadCertModal" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                上传证书
              </button>
              <button @click="loadCertificates" class="btn-secondary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                刷新
              </button>
            </div>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr class="border-b border-border-primary">
                  <th class="text-left py-3 px-4">证书名称</th>
                  <th class="text-left py-3 px-4">域名</th>
                  <th class="text-left py-3 px-4">类型</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">过期时间</th>
                  <th class="text-left py-3 px-4">剩余天数</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="cert in certificates" :key="cert.cert_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4">{{ cert.cert_name }}</td>
                  <td class="py-3 px-4 font-mono text-sm">{{ cert.domain_name }}</td>
                  <td class="py-3 px-4 text-sm">{{ getCertTypeLabel(cert.cert_type) }}</td>
                  <td class="py-3 px-4">
                    <span :class="getCertStatusClass(cert.status)">
                      {{ getCertStatusLabel(cert.status) }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ formatDate(cert.expires_at) }}</td>
                  <td class="py-3 px-4">
                    <span :class="cert.days_before_expiry <= 30 ? 'text-danger' : 'text-success'">
                      {{ cert.days_before_expiry }} 天
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <button @click="viewCertDetails(cert)" class="text-primary hover:text-blue-400 mr-2">详情</button>
                    <button @click="deleteCertificate(cert.cert_id)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="certificates.length === 0" class="text-center py-8 text-text-secondary">
              暂无证书数据
            </div>
          </div>
        </div>
      </div>
"""

    # Insert before refresh tab
    content = content.replace(
        '      <div v-if="activeTab === \'refresh\'" class="space-y-6">',
        rbac_tab_content + '\n      <div v-if="activeTab === \'refresh\'" class="space-y-6">'
    )

    # Add state variables before the existing state
    state_vars = """
// RBAC state
const roles = ref([])
const showRoleModal = ref(false)
const roleForm = ref({
  role_name: '',
  role_code: '',
  description: '',
  is_active: true
})
const isEditingRole = ref(false)
const editingRoleId = ref(null)

// SSL Certificate state
const certificates = ref([])
const showCertModal = ref(false)

"""

    # Insert after "const activeTab = ref('version')"
    content = content.replace(
        "const activeTab = ref('version')\nconst tabs = [",
        "const activeTab = ref('version')\n" + state_vars + "const tabs = ["
    )

    # Add functions before the existing functions
    functions = """
// RBAC Functions
async function loadRoles() {
  try {
    const response = await api.get('/api/v1/rbac/roles')
    roles.value = response.data
  } catch (error) {
    console.error('Failed to load roles:', error)
    alert('加载角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openAddRoleModal() {
  roleForm.value = {
    role_name: '',
    role_code: '',
    description: '',
    is_active: true
  }
  isEditingRole.value = false
  showRoleModal.value = true
}

function editRole(role) {
  roleForm.value = {
    role_name: role.role_name,
    role_code: role.role_code,
    description: role.description || '',
    is_active: role.is_active
  }
  editingRoleId.value = role.role_id
  isEditingRole.value = true
  showRoleModal.value = true
}

async function saveRole() {
  try {
    if (isEditingRole.value) {
      await api.put(`/api/v1/rbac/roles/${editingRoleId.value}`, roleForm.value)
      alert('角色更新成功')
    } else {
      await api.post('/api/v1/rbac/roles', roleForm.value)
      alert('角色创建成功')
    }
    showRoleModal.value = false
    await loadRoles()
  } catch (error) {
    console.error('Failed to save role:', error)
    alert('保存角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function deleteRole(roleId) {
  if (!confirm('确定要删除此角色吗？')) return
  try {
    await api.delete(`/api/v1/rbac/roles/${roleId}`)
    alert('角色删除成功')
    await loadRoles()
  } catch (error) {
    console.error('Failed to delete role:', error)
    alert('删除角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

// SSL Certificate Functions
async function loadCertificates() {
  try {
    const response = await api.get('/api/v1/ssl/certificates')
    certificates.value = response.data
  } catch (error) {
    console.error('Failed to load certificates:', error)
    alert('加载证书失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openUploadCertModal() {
  showCertModal.value = true
}

async function deleteCertificate(certId) {
  if (!confirm('确定要删除此证书吗？')) return
  try {
    await api.delete(`/api/v1/ssl/certificates/${certId}`)
    alert('证书删除成功')
    await loadCertificates()
  } catch (error) {
    console.error('Failed to delete certificate:', error)
    alert('删除证书失败: ' + (error.response?.data?.detail || error.message))
  }
}

function viewCertDetails(cert) {
  alert(`证书详情:\\n域名: ${cert.domain_name}\\n颁发者: ${cert.issuer || 'N/A'}\\n主题: ${cert.subject || 'N/A'}\\n序列号: ${cert.serial_number || 'N/A'}`)
}

function getCertTypeLabel(type) {
  const labels = {
    'self_signed': '自签名',
    'ca_signed': 'CA签名',
    'letsencrypt': "Let's Encrypt"
  }
  return labels[type] || type
}

function getCertStatusLabel(status) {
  const labels = {
    'active': '已激活',
    'inactive': '未激活',
    'expired': '已过期',
    'expiring_soon': '即将过期'
  }
  return labels[status] || status
}

function getCertStatusClass(status) {
  const classes = {
    'active': 'text-success',
    'inactive': 'text-text-secondary',
    'expired': 'text-danger',
    'expiring_soon': 'text-warning'
  }
  return classes[status] || 'text-text-secondary'
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

"""

    # Insert before "// Refresh management state"
    content = content.replace(
        "// Refresh management state",
        functions + "\n// Refresh management state"
    )

    # Add load calls in onMounted
    content = content.replace(
        "onMounted(async () => {",
        """onMounted(async () => {
  loadRoles()
  loadCertificates()"""
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added RBAC and SSL management features to {file_path}")

if __name__ == '__main__':
    add_management_features()
