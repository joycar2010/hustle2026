#!/usr/bin/env python3
"""
Script to add User Management to System.vue
"""

def add_user_management():
    file_path = 'frontend/src/views/System.vue'

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add users tab in tabs array
    content = content.replace(
        "  { id: 'security', label: '安全组件管理' },",
        "  { id: 'security', label: '安全组件管理' },\n  { id: 'users', label: '用户管理' },"
    )

    # Add user management tab content before refresh tab
    users_tab_content = '''
      <!-- 用户管理 Tab -->
      <div v-if="activeTab === 'users'" class="space-y-6">
        <div class="card">
          <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold">用户管理</h2>
            <div class="flex space-x-3">
              <button @click="openAddUserModal" class="btn-primary">
                <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                </svg>
                添加用户
              </button>
              <button @click="loadUsers" class="btn-secondary">
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
                  <th class="text-left py-3 px-4">用户名</th>
                  <th class="text-left py-3 px-4">邮箱</th>
                  <th class="text-left py-3 px-4">角色</th>
                  <th class="text-left py-3 px-4">RBAC角色</th>
                  <th class="text-left py-3 px-4">状态</th>
                  <th class="text-left py-3 px-4">创建时间</th>
                  <th class="text-left py-3 px-4">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in users" :key="user.user_id" class="border-b border-border-secondary hover:bg-dark-50">
                  <td class="py-3 px-4 font-medium">{{ user.username }}</td>
                  <td class="py-3 px-4 text-text-secondary text-sm">{{ user.email }}</td>
                  <td class="py-3 px-4">
                    <span class="px-2 py-1 rounded text-xs bg-primary text-white">
                      {{ user.role }}
                    </span>
                  </td>
                  <td class="py-3 px-4">
                    <div class="flex flex-wrap gap-1">
                      <span
                        v-for="rbacRole in user.rbac_roles"
                        :key="rbacRole.role_id"
                        class="px-2 py-1 rounded text-xs bg-success text-white"
                      >
                        {{ rbacRole.role_name }}
                      </span>
                      <span v-if="!user.rbac_roles || user.rbac_roles.length === 0" class="text-xs text-text-secondary">
                        未分配
                      </span>
                    </div>
                  </td>
                  <td class="py-3 px-4">
                    <span :class="user.is_active ? 'text-success' : 'text-danger'">
                      {{ user.is_active ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td class="py-3 px-4 text-text-secondary text-sm">
                    {{ formatDate(user.create_time) }}
                  </td>
                  <td class="py-3 px-4">
                    <button @click="editUser(user)" class="text-primary hover:text-blue-400 mr-2">编辑</button>
                    <button @click="assignUserRoles(user)" class="text-success hover:text-green-400 mr-2">分配角色</button>
                    <button @click="toggleUserStatus(user)" :class="user.is_active ? 'text-warning hover:text-yellow-400 mr-2' : 'text-success hover:text-green-400 mr-2'">
                      {{ user.is_active ? '禁用' : '启用' }}
                    </button>
                    <button @click="deleteUser(user)" class="text-danger hover:text-red-400">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="users.length === 0" class="text-center py-8 text-text-secondary">
              暂无用户数据
            </div>
          </div>
        </div>

        <!-- Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">总用户数</div>
            <div class="text-2xl font-bold">{{ users.length }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">启用用户</div>
            <div class="text-2xl font-bold text-success">{{ activeUsersCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">禁用用户</div>
            <div class="text-2xl font-bold text-danger">{{ inactiveUsersCount }}</div>
          </div>
          <div class="bg-dark-200 rounded p-4">
            <div class="text-sm text-text-secondary mb-1">管理员</div>
            <div class="text-2xl font-bold text-warning">{{ adminUsersCount }}</div>
          </div>
        </div>
      </div>
'''

    # Insert before refresh tab
    content = content.replace(
        "      <div v-if=\"activeTab === 'refresh'\" class=\"space-y-6\">",
        users_tab_content + "\n      <div v-if=\"activeTab === 'refresh'\" class=\"space-y-6\">"
    )

    # Add state variables
    users_state = '''
// User Management state
const users = ref([])
const showUserModal = ref(false)
const showUserRolesModal = ref(false)
const isEditingUser = ref(false)
const currentUser = ref(null)
const userForm = ref({
  username: '',
  email: '',
  password: '',
  role: '交易员',
  is_active: true
})
const selectedUserRoles = ref([])

const activeUsersCount = computed(() =>
  users.value.filter(u => u.is_active).length
)

const inactiveUsersCount = computed(() =>
  users.value.filter(u => !u.is_active).length
)

const adminUsersCount = computed(() =>
  users.value.filter(u => u.role === '管理员').length
)

'''

    # Insert after security component state
    content = content.replace(
        "const componentConfigJson = computed({",
        users_state + "const componentConfigJson = computed({"
    )

    # Add functions
    users_functions = '''
// User Management Functions
async function loadUsers() {
  try {
    const response = await api.get('/api/v1/users/')
    users.value = response.data
  } catch (error) {
    console.error('Failed to load users:', error)
    alert('加载用户失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openAddUserModal() {
  userForm.value = {
    username: '',
    email: '',
    password: '',
    role: '交易员',
    is_active: true
  }
  isEditingUser.value = false
  showUserModal.value = true
}

function editUser(user) {
  userForm.value = {
    username: user.username,
    email: user.email,
    password: '',
    role: user.role,
    is_active: user.is_active
  }
  currentUser.value = user
  isEditingUser.value = true
  showUserModal.value = true
}

async function saveUser() {
  try {
    if (!userForm.value.username || !userForm.value.email) {
      alert('请填写用户名和邮箱')
      return
    }

    if (!isEditingUser.value && !userForm.value.password) {
      alert('请填写密码')
      return
    }

    if (isEditingUser.value) {
      const updateData = {
        email: userForm.value.email,
        role: userForm.value.role,
        is_active: userForm.value.is_active
      }
      if (userForm.value.password) {
        updateData.password = userForm.value.password
      }
      await api.put(`/api/v1/users/${currentUser.value.user_id}`, updateData)
      alert('用户更新成功')
    } else {
      await api.post('/api/v1/users/', userForm.value)
      alert('用户创建成功')
    }

    showUserModal.value = false
    await loadUsers()
  } catch (error) {
    console.error('Failed to save user:', error)
    alert('保存用户失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function toggleUserStatus(user) {
  const action = user.is_active ? '禁用' : '启用'
  if (!confirm(`确定要${action}用户"${user.username}"吗？`)) return

  try {
    await api.put(`/api/v1/users/${user.user_id}`, {
      is_active: !user.is_active
    })
    alert(`用户${action}成功`)
    await loadUsers()
  } catch (error) {
    console.error('Failed to toggle user status:', error)
    alert(`${action}用户失败: ` + (error.response?.data?.detail || error.message))
  }
}

async function deleteUser(user) {
  if (!confirm(`确定要删除用户"${user.username}"吗？此操作不可恢复！`)) return

  try {
    await api.delete(`/api/v1/users/${user.user_id}`)
    alert('用户删除成功')
    await loadUsers()
  } catch (error) {
    console.error('Failed to delete user:', error)
    alert('删除用户失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function assignUserRoles(user) {
  try {
    currentUser.value = user

    // Load all roles if not loaded
    if (roles.value.length === 0) {
      await loadRoles()
    }

    // Set selected roles
    selectedUserRoles.value = user.rbac_roles ? user.rbac_roles.map(r => r.role_id) : []

    showUserRolesModal.value = true
  } catch (error) {
    console.error('Failed to load user roles:', error)
    alert('加载用户角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function saveUserRoles() {
  try {
    await api.post(`/api/v1/rbac/users/${currentUser.value.user_id}/roles`, {
      role_ids: selectedUserRoles.value
    })

    alert('角色分配成功')
    showUserRolesModal.value = false
    await loadUsers()
  } catch (error) {
    console.error('Failed to save user roles:', error)
    alert('保存用户角色失败: ' + (error.response?.data?.detail || error.message))
  }
}

'''

    # Insert before Security Component Functions
    content = content.replace(
        '\n// Security Component Functions',
        '\n' + users_functions + '// Security Component Functions'
    )

    # Add to onMounted
    content = content.replace(
        'onMounted(async () => {\n  loadRoles()\n  loadCertificates()\n  loadAllPermissions()\n  loadSecurityComponents()',
        'onMounted(async () => {\n  loadRoles()\n  loadCertificates()\n  loadAllPermissions()\n  loadSecurityComponents()\n  loadUsers()'
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Successfully added user management to {file_path}")

if __name__ == '__main__':
    add_user_management()
