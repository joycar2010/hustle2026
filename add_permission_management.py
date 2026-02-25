#!/usr/bin/env python3
"""
Script to add permission management functionality to RBAC
"""

def add_permission_management():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add permission button in the operations column
    content = content.replace(
        '<button @click="editRole(role)" class="text-primary hover:text-blue-400 mr-2">编辑</button>',
        '''<button @click="editRole(role)" class="text-primary hover:text-blue-400 mr-2">编辑</button>
                    <button @click="managePermissions(role)" class="text-success hover:text-green-400 mr-2">权限</button>'''
    )

    # Add permission modal HTML before the closing </template> tag
    permission_modal = '''
    <!-- Permission Management Modal -->
    <div v-if="showPermissionModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-dark-100 rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <h3 class="text-xl font-bold mb-4">权限管理 - {{ currentRole?.role_name }}</h3>

        <div class="mb-4 flex justify-between items-center">
          <div class="text-sm text-text-secondary">
            已选择 {{ selectedPermissions.length }} 个权限
          </div>
          <div class="flex space-x-2">
            <button @click="selectAllPermissions" class="btn-secondary text-sm">全选</button>
            <button @click="clearAllPermissions" class="btn-secondary text-sm">清空</button>
          </div>
        </div>

        <!-- Permission Categories -->
        <div class="space-y-4">
          <!-- API Permissions -->
          <div class="bg-dark-200 rounded p-4">
            <h4 class="font-bold mb-3 flex items-center">
              <svg class="w-5 h-5 mr-2 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              API接口权限
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              <div v-for="perm in apiPermissions" :key="perm.permission_id" class="flex items-start">
                <input
                  type="checkbox"
                  :id="'perm-' + perm.permission_id"
                  :value="perm.permission_id"
                  v-model="selectedPermissions"
                  class="mt-1 mr-2"
                />
                <label :for="'perm-' + perm.permission_id" class="text-sm cursor-pointer">
                  <div class="font-medium">{{ perm.permission_name }}</div>
                  <div class="text-xs text-text-secondary">{{ perm.description || perm.resource_path }}</div>
                </label>
              </div>
            </div>
            <div v-if="apiPermissions.length === 0" class="text-sm text-text-secondary text-center py-4">
              暂无API权限
            </div>
          </div>

          <!-- Menu Permissions -->
          <div class="bg-dark-200 rounded p-4">
            <h4 class="font-bold mb-3 flex items-center">
              <svg class="w-5 h-5 mr-2 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
              菜单导航权限
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              <div v-for="perm in menuPermissions" :key="perm.permission_id" class="flex items-start">
                <input
                  type="checkbox"
                  :id="'perm-' + perm.permission_id"
                  :value="perm.permission_id"
                  v-model="selectedPermissions"
                  class="mt-1 mr-2"
                />
                <label :for="'perm-' + perm.permission_id" class="text-sm cursor-pointer">
                  <div class="font-medium">{{ perm.permission_name }}</div>
                  <div class="text-xs text-text-secondary">{{ perm.description || perm.resource_path }}</div>
                </label>
              </div>
            </div>
            <div v-if="menuPermissions.length === 0" class="text-sm text-text-secondary text-center py-4">
              暂无菜单权限
            </div>
          </div>

          <!-- Button Permissions -->
          <div class="bg-dark-200 rounded p-4">
            <h4 class="font-bold mb-3 flex items-center">
              <svg class="w-5 h-5 mr-2 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" />
              </svg>
              按钮操作权限
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              <div v-for="perm in buttonPermissions" :key="perm.permission_id" class="flex items-start">
                <input
                  type="checkbox"
                  :id="'perm-' + perm.permission_id"
                  :value="perm.permission_id"
                  v-model="selectedPermissions"
                  class="mt-1 mr-2"
                />
                <label :for="'perm-' + perm.permission_id" class="text-sm cursor-pointer">
                  <div class="font-medium">{{ perm.permission_name }}</div>
                  <div class="text-xs text-text-secondary">{{ perm.description || perm.resource_path }}</div>
                </label>
              </div>
            </div>
            <div v-if="buttonPermissions.length === 0" class="text-sm text-text-secondary text-center py-4">
              暂无按钮权限
            </div>
          </div>
        </div>

        <div class="flex justify-end space-x-3 mt-6">
          <button @click="closePermissionModal" class="btn-secondary">取消</button>
          <button @click="savePermissions" class="btn-primary">保存权限</button>
        </div>
      </div>
    </div>
'''

    # Insert before the last </template> tag
    last_template_pos = content.rfind('</template>')
    content = content[:last_template_pos] + permission_modal + '\n' + content[last_template_pos:]

    # Add state variables for permission management
    permission_state = '''
// Permission management state
const showPermissionModal = ref(false)
const currentRole = ref(null)
const allPermissions = ref([])
const selectedPermissions = ref([])

const apiPermissions = computed(() =>
  allPermissions.value.filter(p => p.resource_type === 'api')
)
const menuPermissions = computed(() =>
  allPermissions.value.filter(p => p.resource_type === 'menu')
)
const buttonPermissions = computed(() =>
  allPermissions.value.filter(p => p.resource_type === 'button')
)

'''

    # Insert after certForm state
    content = content.replace(
        "const certForm = ref({\n  cert_name: '',\n  domain_name: '',\n  cert_type: 'ca_signed',\n  cert_content: '',\n  key_content: '',\n  auto_renew: false\n})\n\n",
        "const certForm = ref({\n  cert_name: '',\n  domain_name: '',\n  cert_type: 'ca_signed',\n  cert_content: '',\n  key_content: '',\n  auto_renew: false\n})\n\n" + permission_state
    )

    # Add permission management functions
    permission_functions = '''
// Permission Management Functions
async function loadAllPermissions() {
  try {
    const response = await api.get('/api/v1/rbac/permissions')
    allPermissions.value = response.data
  } catch (error) {
    console.error('Failed to load permissions:', error)
  }
}

async function managePermissions(role) {
  try {
    currentRole.value = role

    // Load all permissions if not loaded
    if (allPermissions.value.length === 0) {
      await loadAllPermissions()
    }

    // Load role's current permissions
    const response = await api.get(`/api/v1/rbac/roles/${role.role_id}`)
    selectedPermissions.value = response.data.permissions.map(p => p.permission_id)

    showPermissionModal.value = true
  } catch (error) {
    console.error('Failed to load role permissions:', error)
    alert('加载角色权限失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function savePermissions() {
  try {
    await api.post(`/api/v1/rbac/roles/${currentRole.value.role_id}/permissions`, {
      permission_ids: selectedPermissions.value
    })

    alert('权限保存成功')
    closePermissionModal()
  } catch (error) {
    console.error('Failed to save permissions:', error)
    alert('保存权限失败: ' + (error.response?.data?.detail || error.message))
  }
}

function closePermissionModal() {
  showPermissionModal.value = false
  currentRole.value = null
  selectedPermissions.value = []
}

function selectAllPermissions() {
  selectedPermissions.value = allPermissions.value.map(p => p.permission_id)
}

function clearAllPermissions() {
  selectedPermissions.value = []
}

'''

    # Insert before uploadCertificate function
    content = content.replace(
        '\nasync function uploadCertificate() {',
        '\n' + permission_functions + 'async function uploadCertificate() {'
    )

    # Add loadAllPermissions to onMounted
    content = content.replace(
        'onMounted(async () => {\n  loadRoles()\n  loadCertificates()',
        'onMounted(async () => {\n  loadRoles()\n  loadCertificates()\n  loadAllPermissions()'
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added permission management functionality to {file_path}")

if __name__ == '__main__':
    add_permission_management()
