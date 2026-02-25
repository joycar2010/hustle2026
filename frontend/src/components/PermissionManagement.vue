<template>
  <div>
    <div class="flex justify-end mb-4">
      <button @click="showCreateDialog = true" class="btn-primary">
        <span class="mr-2">+</span> 创建权限
      </button>
    </div>

    <!-- Permissions Table Card -->
    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-semibold">权限列表</h2>
        <div class="text-sm text-text-tertiary">
          共 {{ permissions.length }} 个权限
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="loading" class="text-center py-12">
        <div class="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
        <div class="text-text-tertiary mt-4">加载中...</div>
      </div>

      <!-- Permissions Table -->
      <div v-else class="overflow-x-auto">
        <table class="min-w-full">
          <thead>
            <tr class="border-b border-border-secondary">
              <th class="px-6 py-3 text-left table-header">权限名称</th>
              <th class="px-6 py-3 text-left table-header">权限代码</th>
              <th class="px-6 py-3 text-left table-header">资源类型</th>
              <th class="px-6 py-3 text-left table-header">资源路径</th>
              <th class="px-6 py-3 text-left table-header">HTTP方法</th>
              <th class="px-6 py-3 text-left table-header">状态</th>
              <th class="px-6 py-3 text-right table-header">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="permission in permissions" :key="permission.permission_id" class="table-row">
              <td class="px-6 py-4 whitespace-nowrap font-medium">
                {{ permission.permission_name }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <code class="bg-dark-100 px-2 py-1 rounded text-sm text-primary">
                  {{ permission.permission_code }}
                </code>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span :class="getResourceTypeBadge(permission.resource_type)">
                  {{ permission.resource_type }}
                </span>
              </td>
              <td class="px-6 py-4 text-text-secondary text-sm">
                {{ permission.resource_path || '-' }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span v-if="permission.http_method" class="badge bg-info/20 text-info text-xs">
                  {{ permission.http_method }}
                </span>
                <span v-else class="text-text-tertiary">-</span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span :class="permission.is_active ? 'badge-success' : 'badge-danger'">
                  {{ permission.is_active ? '启用' : '禁用' }}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-right text-sm">
                <button
                  @click="editPermission(permission)"
                  class="text-success hover:text-success/80 mr-3 transition-colors"
                  title="编辑权限"
                >
                  编辑
                </button>
                <button
                  @click="deletePermission(permission)"
                  class="text-danger hover:text-danger/80 transition-colors"
                  title="删除权限"
                >
                  删除
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Empty State -->
        <div v-if="permissions.length === 0" class="text-center py-12">
          <div class="text-text-tertiary text-lg mb-2">暂无权限数据</div>
          <div class="text-text-tertiary text-sm">点击"创建权限"按钮添加新权限</div>
        </div>
      </div>
    </div>

    <!-- Create/Edit Permission Dialog -->
    <div
      v-if="showCreateDialog || showEditDialog"
      class="fixed inset-0 bg-black/70 flex items-center justify-center z-50"
      @click.self="closeDialog"
    >
      <div class="card-elevated w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-6">
          <h3 class="text-xl font-semibold">
            {{ showEditDialog ? '编辑权限' : '创建权限' }}
          </h3>
          <button
            @click="closeDialog"
            class="text-text-tertiary hover:text-text-primary transition-colors"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form @submit.prevent="handleSubmit">
          <div class="space-y-4">
            <!-- Permission Name -->
            <div>
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                权限名称 <span class="text-danger">*</span>
              </label>
              <input
                v-model="formData.permission_name"
                type="text"
                required
                placeholder="例如：查看用户列表"
                class="input-field"
              />
            </div>

            <!-- Permission Code -->
            <div>
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                权限代码 <span class="text-danger">*</span>
              </label>
              <input
                v-model="formData.permission_code"
                type="text"
                required
                :disabled="showEditDialog"
                placeholder="例如：user:list"
                class="input-field"
                :class="{ 'opacity-50 cursor-not-allowed': showEditDialog }"
              />
              <p class="text-xs text-text-tertiary mt-1">
                {{ showEditDialog ? '权限代码创建后不可修改' : '使用英文字母、冒号和下划线' }}
              </p>
            </div>

            <!-- Resource Type -->
            <div>
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                资源类型 <span class="text-danger">*</span>
              </label>
              <select
                v-model="formData.resource_type"
                required
                :disabled="showEditDialog"
                class="input-field"
                :class="{ 'opacity-50 cursor-not-allowed': showEditDialog }"
              >
                <option value="">请选择资源类型</option>
                <option value="api">API接口</option>
                <option value="menu">菜单</option>
                <option value="button">按钮</option>
              </select>
            </div>

            <!-- Resource Path -->
            <div>
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                资源路径
              </label>
              <input
                v-model="formData.resource_path"
                type="text"
                :disabled="showEditDialog"
                placeholder="例如：/api/v1/users"
                class="input-field"
                :class="{ 'opacity-50 cursor-not-allowed': showEditDialog }"
              />
            </div>

            <!-- HTTP Method -->
            <div v-if="formData.resource_type === 'api'">
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                HTTP方法
              </label>
              <select
                v-model="formData.http_method"
                :disabled="showEditDialog"
                class="input-field"
                :class="{ 'opacity-50 cursor-not-allowed': showEditDialog }"
              >
                <option value="">请选择HTTP方法</option>
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="DELETE">DELETE</option>
                <option value="PATCH">PATCH</option>
              </select>
            </div>

            <!-- Description -->
            <div>
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                权限描述
              </label>
              <textarea
                v-model="formData.description"
                rows="3"
                placeholder="描述该权限的用途和范围"
                class="input-field resize-none"
              ></textarea>
            </div>

            <!-- Sort Order -->
            <div>
              <label class="block text-sm font-medium mb-2 text-text-secondary">
                排序顺序
              </label>
              <input
                v-model.number="formData.sort_order"
                type="number"
                min="0"
                placeholder="0"
                class="input-field"
              />
            </div>

            <!-- Active Status -->
            <div class="flex items-center">
              <label class="relative inline-flex items-center cursor-pointer">
                <input
                  v-model="formData.is_active"
                  type="checkbox"
                  class="sr-only peer"
                />
                <div class="w-11 h-6 bg-dark-100 peer-focus:outline-none rounded-full peer
                            peer-checked:after:translate-x-full peer-checked:after:border-white
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                            after:bg-white after:border-gray-300 after:border after:rounded-full
                            after:h-5 after:w-5 after:transition-all peer-checked:bg-success">
                </div>
                <span class="ml-3 text-sm text-text-secondary">启用权限</span>
              </label>
            </div>
          </div>

          <!-- Dialog Actions -->
          <div class="flex justify-end gap-3 mt-6 pt-4 border-t border-border-secondary">
            <button
              type="button"
              @click="closeDialog"
              class="btn-secondary"
            >
              取消
            </button>
            <button
              type="submit"
              class="btn-primary"
              :disabled="submitting"
            >
              {{ submitting ? '提交中...' : (showEditDialog ? '更新权限' : '创建权限') }}
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
const { permissions, loading } = storeToRefs(rbacStore)

const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const submitting = ref(false)

const formData = ref({
  permission_name: '',
  permission_code: '',
  resource_type: '',
  resource_path: '',
  http_method: '',
  description: '',
  sort_order: 0,
  is_active: true
})
const editingPermissionId = ref(null)

onMounted(async () => {
  await rbacStore.fetchPermissions()
})

const getResourceTypeBadge = (type) => {
  const badges = {
    api: 'badge bg-primary/20 text-primary',
    menu: 'badge bg-success/20 text-success',
    button: 'badge bg-warning/20 text-warning'
  }
  return badges[type] || 'badge bg-dark-100 text-text-secondary'
}

const editPermission = (permission) => {
  formData.value = {
    permission_name: permission.permission_name,
    permission_code: permission.permission_code,
    resource_type: permission.resource_type,
    resource_path: permission.resource_path || '',
    http_method: permission.http_method || '',
    description: permission.description || '',
    sort_order: permission.sort_order || 0,
    is_active: permission.is_active
  }
  editingPermissionId.value = permission.permission_id
  showEditDialog.value = true
}

const deletePermission = async (permission) => {
  if (confirm(`确定要删除权限 "${permission.permission_name}" 吗？\n\n此操作不可恢复！`)) {
    try {
      await rbacStore.deletePermission(permission.permission_id)
      alert('✓ 权限删除成功')
      await rbacStore.fetchPermissions()
    } catch (err) {
      alert('✗ 权限删除失败: ' + (err.message || '未知错误'))
    }
  }
}

const handleSubmit = async () => {
  if (submitting.value) return

  submitting.value = true
  try {
    if (showEditDialog.value) {
      await rbacStore.updatePermission(editingPermissionId.value, {
        permission_name: formData.value.permission_name,
        description: formData.value.description,
        sort_order: formData.value.sort_order,
        is_active: formData.value.is_active
      })
      alert('✓ 权限更新成功')
    } else {
      await rbacStore.createPermission(formData.value)
      alert('✓ 权限创建成功')
    }
    await rbacStore.fetchPermissions()
    closeDialog()
  } catch (err) {
    alert('✗ ' + (showEditDialog.value ? '权限更新失败' : '权限创建失败') + ': ' + (err.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}

const closeDialog = () => {
  showCreateDialog.value = false
  showEditDialog.value = false
  formData.value = {
    permission_name: '',
    permission_code: '',
    resource_type: '',
    resource_path: '',
    http_method: '',
    description: '',
    sort_order: 0,
    is_active: true
  }
  editingPermissionId.value = null
}
</script>

