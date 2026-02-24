import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useRbacStore = defineStore('rbac', () => {
  // State
  const roles = ref([])
  const permissions = ref([])
  const currentRole = ref(null)
  const loading = ref(false)
  const error = ref(null)

  // Computed
  const roleCount = computed(() => roles.value.length)
  const permissionCount = computed(() => permissions.value.length)

  // Actions
  const fetchRoles = async () => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get('/api/v1/rbac/roles')
      roles.value = response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取角色列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchPermissions = async () => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get('/api/v1/rbac/permissions')
      permissions.value = response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取权限列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchRoleById = async (roleId) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/rbac/roles/${roleId}`)
      currentRole.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取角色详情失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const createRole = async (roleData) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.post('/api/v1/rbac/roles', roleData)
      roles.value.push(response.data)
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '创建角色失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const updateRole = async (roleId, roleData) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.put(`/api/v1/rbac/roles/${roleId}`, roleData)
      const index = roles.value.findIndex(r => r.role_id === roleId)
      if (index !== -1) {
        roles.value[index] = response.data
      }
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '更新角色失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const deleteRole = async (roleId) => {
    loading.value = true
    error.value = null
    try {
      await axios.delete(`/api/v1/rbac/roles/${roleId}`)
      roles.value = roles.value.filter(r => r.role_id !== roleId)
    } catch (err) {
      error.value = err.response?.data?.detail || '删除角色失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const copyRole = async (roleId, newRoleName) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.post(`/api/v1/rbac/roles/${roleId}/copy`, {
        new_role_name: newRoleName
      })
      roles.value.push(response.data)
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '复制角色失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const assignPermissions = async (roleId, permissionIds) => {
    loading.value = true
    error.value = null
    try {
      await axios.post(`/api/v1/rbac/roles/${roleId}/permissions`, {
        permission_ids: permissionIds
      })
    } catch (err) {
      error.value = err.response?.data?.detail || '分配权限失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const assignUserRole = async (userId, roleIds) => {
    loading.value = true
    error.value = null
    try {
      await axios.post(`/api/v1/rbac/users/${userId}/roles`, {
        role_ids: roleIds
      })
    } catch (err) {
      error.value = err.response?.data?.detail || '分配用户角色失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const getUserPermissions = async (userId) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/rbac/users/${userId}/permissions`)
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取用户权限失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    roles,
    permissions,
    currentRole,
    loading,
    error,
    roleCount,
    permissionCount,
    fetchRoles,
    fetchPermissions,
    fetchRoleById,
    createRole,
    updateRole,
    deleteRole,
    copyRole,
    assignPermissions,
    assignUserRole,
    getUserPermissions
  }
})
