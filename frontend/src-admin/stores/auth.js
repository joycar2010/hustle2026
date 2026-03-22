import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api.js'

export const useAuthStore = defineStore('auth', () => {
  // 过滤历史缓存中的 "null" 字符串
  const _cachedRole = localStorage.getItem('admin_role')
  const _validRole = (_cachedRole && _cachedRole !== 'null' && _cachedRole !== 'undefined') ? _cachedRole : null

  const token = ref(localStorage.getItem('admin_token') || null)
  const user = ref(null)
  const userRole = ref(_validRole)

  const isAuthenticated = computed(() => !!token.value)

  async function login(username, password) {
    try {
      const response = await api.post('/api/v1/auth/login', { username, password })
      token.value = response.data.access_token
      localStorage.setItem('admin_token', token.value)

      user.value = {
        user_id: response.data.user_id,
        username: response.data.username,
      }

      await fetchUser()
      return true
    } catch (error) {
      console.error('Login failed:', error)
      return false
    }
  }

  async function fetchUser() {
    try {
      const response = await api.get('/api/v1/users/me')
      user.value = response.data
      const d = response.data

      // 1. 优先取 RBAC 角色（user_roles 关联表，如 '系统管理员'）
      if (d.rbac_roles && d.rbac_roles.length > 0) {
        userRole.value = d.rbac_roles[0].role_name || d.rbac_roles[0]
      } else {
        // 2. 回退到 users.role 字段（如 '管理员'）
        userRole.value = d.role || null
      }

      // 3. 若 /users/me 未携带 rbac_roles，单独查一次 RBAC 角色
      if (!userRole.value) {
        try {
          const uid = d.user_id
          const rbacRes = await api.get(`/api/v1/rbac/users/${uid}/roles`)
          const rbacRoles = rbacRes.data || []
          if (rbacRoles.length > 0) {
            userRole.value = rbacRoles[0].role?.role_name
              || rbacRoles[0].role_name
              || rbacRoles[0]
          }
        } catch { /* RBAC 查询失败时保留 users.role */ }
      }

      localStorage.setItem('admin_role', userRole.value || '')
    } catch (error) {
      console.error('Failed to fetch user info:', error)
    }
  }

  function logout() {
    token.value = null
    user.value = null
    userRole.value = null
    localStorage.removeItem('admin_token')
    localStorage.removeItem('admin_role')
  }

  return { token, user, userRole, isAuthenticated, login, logout, fetchUser }
})
