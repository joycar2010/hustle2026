import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { reloadTradingPairs } from '@/composables/useTradingPair'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || null)
  const user = ref(null)

  const isAuthenticated = computed(() => !!token.value)

  async function login(username, password) {
    try {
      const response = await api.post('/api/v1/auth/login', {
        username,
        password
      })

      token.value = response.data.access_token
      localStorage.setItem('token', token.value)

      // Store user data from login response
      user.value = {
        user_id: response.data.user_id,
        username: response.data.username,
        email: response.data.email || `${response.data.username}@hustle.com`
      }

      // Refresh the global trading-pair list so the navbar selector reflects
      // THIS user's configured pairs (not the prior session's). Non-blocking.
      reloadTradingPairs(true).catch(() => {})

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
    } catch (error) {
      console.error('Failed to fetch user:', error)
    }
  }

  function updateUser(userData) {
    user.value = { ...user.value, ...userData }
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
    // Reset the pair cache so the next user (or login page) doesn't see
    // the outgoing user's configured set.
    reloadTradingPairs(true).catch(() => {})
  }

  return {
    token,
    user,
    isAuthenticated,
    login,
    logout,
    fetchUser,
    updateUser
  }
})
