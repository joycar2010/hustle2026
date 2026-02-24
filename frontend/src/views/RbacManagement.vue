<template>
  <div class="rbac-management p-6">
    <div class="flex justify-between items-center mb-6">
      <h1 class="text-2xl font-bold">角色权限管理</h1>
      <button
        @click="showCreateDialog = true"
        class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded"
      >
        创建角色
      </button>
    </div>

    <div v-if="error" class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
      {{ error }}
    </div>

    <div class="grid grid-cols-1 gap-6">
      <div class="bg-white rounded-lg shadow">
        <div class="p-4 border-b">
          <h2 class="text-lg font-semibold">角色列表</h2>
        </div>
        <div class="p-4">
          <div v-if="loading" class="text-center py-8">
            <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
          </div>
          <div v-else>
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">角色名称</th>
                  <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">角色代码</th>
                  <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">描述</th>
                  <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态</th>
                  <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
                </tr>
              </thead>
              <tbody class="bg-white divide-y divide-gray-200">
                <tr v-for="role in roles" :key="role.role_id">
                  <td class="px-6 py-4 whitespace-nowrap">{{ role.role_name }}</td>
                  <td class="px-6 py-4 whitespace-nowrap">
                    <code class="bg-gray-100 px-2 py-1 rounded text-sm">{{ role.role_code }}</code>
                  </td>
                  <td class="px-6 py-4">{{ role.description || '-' }}</td>
                  <td class="px-6 py-4 whitespace-nowrap">
                    <span
                      :class="role.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'"
                      class="px-2 py-1 rounded text-xs"
                    >
                      {{ role.is_active ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td class="px-6 py-4 whitespace-nowrap text-sm">
                    <button
                      @click="viewRole(role)"
                      class="text-blue-600 hover:text-blue-900 mr-3"
                    >
                      查看
                    </button>
                    <button
                      @click="editRole(role)"
                      class="text-green-600 hover:text-green-900 mr-3"
                    >
                      编辑
                    </button>
                    <button
                      @click="copyRole(role)"
                      class="text-purple-600 hover:text-purple-900 mr-3"
                    >
                      复制
                    </button>
                    <button
                      v-if="!role.is_system"
                      @click="deleteRole(role)"
                      class="text-red-600 hover:text-red-900"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建/编辑角色对话框 -->
    <div v-if="showCreateDialog || showEditDialog" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div class="bg-white rounded-lg p-6 w-full max-w-md">
        <h3 class="text-lg font-semibold mb-4">{{ showEditDialog ? '编辑角色' : '创建角色' }}</h3>
        <form @submit.prevent="handleSubmit">
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">角色名称</label>
            <input
              v-model="formData.role_name"
              type="text"
              required
              class="w-full border rounded px-3 py-2"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">角色代码</label>
            <input
              v-model="formData.role_code"
              type="text"
              required
              :disabled="showEditDialog"
              class="w-full border rounded px-3 py-2"
            />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-2">描述</label>
            <textarea
              v-model="formData.description"
              rows="3"
              class="w-full border rounded px-3 py-2"
            ></textarea>
          </div>
          <div class="mb-4">
            <label class="flex items-center">
              <input
                v-model="formData.is_active"
                type="checkbox"
                class="mr-2"
              />
              <span class="text-sm">启用角色</span>
            </label>
          </div>
          <div class="flex justify-end gap-2">
            <button
              type="button"
              @click="closeDialog"
              class="px-4 py-2 border rounded hover:bg-gray-100"
            >
              取消
            </button>
            <button
              type="submit"
              class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              {{ showEditDialog ? '更新' : '创建' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRbacStore } from '@/stores/rbac'
import { storeToRefs } from 'pinia'

const rbacStore = useRbacStore()
const { roles, loading, error } = storeToRefs(rbacStore)

const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const formData = ref({
  role_name: '',
  role_code: '',
  description: '',
  is_active: true
})
const editingRoleId = ref(null)

onMounted(async () => {
  await rbacStore.fetchRoles()
})

const viewRole = (role) => {
  // Navigate to role detail page
  console.log('View role:', role)
}

const editRole = (role) => {
  formData.value = {
    role_name: role.role_name,
    role_code: role.role_code,
    description: role.description,
    is_active: role.is_active
  }
  editingRoleId.value = role.role_id
  showEditDialog.value = true
}

const copyRole = async (role) => {
  const newName = prompt('请输入新角色名称:', `${role.role_name} (副本)`)
  if (newName) {
    try {
      await rbacStore.copyRole(role.role_id, newName)
      alert('角色复制成功')
    } catch (err) {
      alert('角色复制失败')
    }
  }
}

const deleteRole = async (role) => {
  if (confirm(`确定要删除角色 "${role.role_name}" 吗？`)) {
    try {
      await rbacStore.deleteRole(role.role_id)
      alert('角色删除成功')
    } catch (err) {
      alert('角色删除失败')
    }
  }
}

const handleSubmit = async () => {
  try {
    if (showEditDialog.value) {
      await rbacStore.updateRole(editingRoleId.value, formData.value)
      alert('角色更新成功')
    } else {
      await rbacStore.createRole(formData.value)
      alert('角色创建成功')
    }
    closeDialog()
  } catch (err) {
    alert(showEditDialog.value ? '角色更新失败' : '角色创建失败')
  }
}

const closeDialog = () => {
  showCreateDialog.value = false
  showEditDialog.value = false
  formData.value = {
    role_name: '',
    role_code: '',
    description: '',
    is_active: true
  }
  editingRoleId.value = null
}
</script>

