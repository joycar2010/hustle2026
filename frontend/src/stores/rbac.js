import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

export const useRbacStore = defineStore('rbac', () => {
  const roles = ref([])
  const permissions = ref([])
  const loading = ref(false)

  async function fetchRoles() {
    loading.value = true
    try {
      const response = await api.get('/api/v1/rbac/roles')
      roles.value = response.data
    } catch (error) {
      console.error('Failed to fetch roles:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchPermissions() {
    loading.value = true
    try {
      const response = await api.get('/api/v1/rbac/permissions')
      permissions.value = response.data
    } catch (error) {
      console.error('Failed to fetch permissions:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchRoleById(roleId) {
    loading.value = true
    try {
      const response = await api.get(`/api/v1/rbac/roles/${roleId}`)
      return response.data
    } catch (error) {
      console.error('Failed to fetch role:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function assignPermissions(roleId, permissionIds) {
    loading.value = true
    try {
      await api.post(`/api/v1/rbac/roles/${roleId}/permissions`, {
        permission_ids: permissionIds
      })
      // Refresh roles after assignment
      await fetchRoles()
    } catch (error) {
      console.error('Failed to assign permissions:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  return {
    roles,
    permissions,
    loading,
    fetchRoles,
    fetchPermissions,
    fetchRoleById,
    assignPermissions
  }
})
