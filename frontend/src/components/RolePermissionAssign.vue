<template>
  <div>
    <div class="card">
      <h2 class="text-xl font-semibold mb-4">角色权限分配</h2>
      <p class="text-text-secondary mb-6">为角色分配权限，控制角色可以访问的功能和资源</p>

      <!-- Role Selection -->
      <div class="mb-6">
        <label class="block text-sm font-medium mb-2 text-text-secondary">
          选择角色 <span class="text-danger">*</span>
        </label>
        <select
          v-model="selectedRoleId"
          @change="loadRolePermissions"
          class="input-field max-w-md"
        >
          <option value="">请选择角色</option>
          <option v-for="role in nonSystemRoles" :key="role.role_id" :value="role.role_id">
            {{ role.role_name }} ({{ role.role_code }})
          </option>
        </select>
        <p class="text-xs text-text-tertiary mt-1">
          系统内置角色不可修改权限
        </p>
      </div>

      <!-- Loading State -->
      <div v-if="loading" class="text-center py-12">
        <div class="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
        <div class="text-text-tertiary mt-4">加载中...</div>
      </div>

      <!-- Permission Selection -->
      <div v-else-if="selectedRoleId" class="space-y-6">
        <!-- Permission Groups -->
        <div v-for="(perms, type) in groupedPermissions" :key="type" class="border border-border-secondary rounded-lg p-4">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-medium flex items-center">
              <span :class="getResourceTypeBadge(type)" class="mr-2">
                {{ getResourceTypeLabel(type) }}
              </span>
              <span class="text-text-tertiary text-sm ml-2">
                ({{ perms.length }} 个权限)
              </span>
            </h3>
            <button
              @click="toggleGroupSelection(type, perms)"
              class="text-sm text-primary hover:text-primary/80 transition-colors"
            >
              {{ isGroupSelected(type, perms) ? '取消全选' : '全选' }}
            </button>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <label
              v-for="permission in perms"
              :key="permission.permission_id"
              class="flex items-start p-3 border border-border-secondary rounded hover:bg-dark-100 cursor-pointer transition-colors"
              :class="{ 'bg-primary/10 border-primary': selectedPermissions.includes(permission.permission_id) }"
            >
              <input
                type="checkbox"
                :value="permission.permission_id"
                v-model="selectedPermissions"
                class="mt-1 mr-3"
              />
              <div class="flex-1 min-w-0">
                <div class="font-medium text-sm">{{ permission.permission_name }}</div>
                <code class="text-xs text-text-tertiary break-all">{{ permission.permission_code }}</code>
                <div v-if="permission.description" class="text-xs text-text-tertiary mt-1">
                  {{ permission.description }}
                </div>
              </div>
            </label>
          </div>
        </div>

        <!-- Save Button -->
        <div class="flex justify-end gap-3 pt-4 border-t border-border-secondary">
          <button
            @click="savePermissions"
            class="btn-primary"
            :disabled="submitting"
          >
            {{ submitting ? '保存中...' : '保存权限配置' }}
          </button>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="text-center py-12">
        <div class="text-text-tertiary text-lg mb-2">请先选择一个角色</div>
        <div class="text-text-tertiary text-sm">选择角色后即可为其分配权限</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRbacStore } from '@/stores/rbac'
import { storeToRefs } from 'pinia'

const rbacStore = useRbacStore()
const { roles, permissions, loading } = storeToRefs(rbacStore)

const selectedRoleId = ref('')
const selectedPermissions = ref([])
const submitting = ref(false)

onMounted(async () => {
  await Promise.all([
    rbacStore.fetchRoles(),
    rbacStore.fetchPermissions()
  ])
})

const nonSystemRoles = computed(() => {
  return roles.value.filter(role => !role.is_system)
})

const groupedPermissions = computed(() => {
  const groups = {}
  permissions.value.forEach(perm => {
    if (!groups[perm.resource_type]) {
      groups[perm.resource_type] = []
    }
    groups[perm.resource_type].push(perm)
  })
  return groups
})

const getResourceTypeBadge = (type) => {
  const badges = {
    api: 'badge bg-primary/20 text-primary',
    menu: 'badge bg-success/20 text-success',
    button: 'badge bg-warning/20 text-warning'
  }
  return badges[type] || 'badge bg-dark-100 text-text-secondary'
}

const getResourceTypeLabel = (type) => {
  const labels = {
    api: 'API接口',
    menu: '菜单',
    button: '按钮'
  }
  return labels[type] || type
}

const isGroupSelected = (type, perms) => {
  return perms.every(p => selectedPermissions.value.includes(p.permission_id))
}

const toggleGroupSelection = (type, perms) => {
  if (isGroupSelected(type, perms)) {
    // Deselect all in group
    perms.forEach(p => {
      const index = selectedPermissions.value.indexOf(p.permission_id)
      if (index > -1) {
        selectedPermissions.value.splice(index, 1)
      }
    })
  } else {
    // Select all in group
    perms.forEach(p => {
      if (!selectedPermissions.value.includes(p.permission_id)) {
        selectedPermissions.value.push(p.permission_id)
      }
    })
  }
}

const loadRolePermissions = async () => {
  if (!selectedRoleId.value) {
    selectedPermissions.value = []
    return
  }

  try {
    const roleData = await rbacStore.fetchRoleById(selectedRoleId.value)
    selectedPermissions.value = roleData.permissions.map(p => p.permission_id)
  } catch (err) {
    alert('✗ 加载角色权限失败: ' + (err.message || '未知错误'))
    selectedPermissions.value = []
  }
}

const savePermissions = async () => {
  if (submitting.value) return

  submitting.value = true
  try {
    await rbacStore.assignPermissions(selectedRoleId.value, selectedPermissions.value)
    alert('✓ 权限配置保存成功')
  } catch (err) {
    alert('✗ 权限配置保存失败: ' + (err.message || '未知错误'))
  } finally {
    submitting.value = false
  }
}
</script>
