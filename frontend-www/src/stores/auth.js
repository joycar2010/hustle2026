import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api.js'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('www_token') || null)
  const user = ref(null)
  const isAuthenticated = computed(() => !!token.value)

  async function login(username, password) {
    try {
      const r = await api.post('/api/v1/auth/login', { username, password })
      token.value = r.data.access_token
      localStorage.setItem('www_token', token.value)
      user.value = { user_id: r.data.user_id, username: r.data.username }
      await fetchUser()
      return true
    } catch { return false }
  }

  async function fetchUser() {
    try {
      const r = await api.get('/api/v1/users/me')
      user.value = r.data
    } catch {}
  }

  function logout() {
    token.value = null; user.value = null
    localStorage.removeItem('www_token')
  }

  return { token, user, isAuthenticated, login, logout, fetchUser }
})
