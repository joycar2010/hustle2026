import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api.js'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('www_token') || null)
  const user = ref(null)
  const subBanner = ref(null)  // { is_sub, multiplier, invested_cny, invested_usdt, current_value_usdt, view_caps }
  const isAuthenticated = computed(() => !!token.value)
  const isSubAccount = computed(() => !!subBanner.value?.is_sub)
  // viewCaps resolution order:
  //   1. /me/subaccount banner — authoritative; covers sub vs parent + admin
  //      role bypass + fund_view_enabled gate. Always trust if present.
  //   2. /users/me as a faster secondary source — fills the ~100ms gap before
  //      the banner lands so authorized parents (fund_view_enabled=true) see
  //      资金流向 immediately on first paint. Sub-accounts and parents
  //      without the permission stay hidden.
  //   3. Nothing loaded yet → hide restricted surfaces (assume worst).
  const viewCaps = computed(() => {
    const caps = subBanner.value?.view_caps
    if (caps) return caps
    const u = user.value
    if (u) {
      // Admin roles always see everything.
      const ADMIN_ROLES = ['超级管理员', '系统管理员', '安全管理员', '管理员',
                           'admin', 'super_admin']
      const isAdmin = ADMIN_ROLES.includes(u.role)
      // Sub-accounts NEVER get fund_flow regardless of users-row flag.
      const isSub = !!u.is_subaccount
      const fundFlow = isAdmin ? true : (isSub ? false : !!u.fund_view_enabled)
      return { fund_flow: fundFlow, can_trade: true, can_edit_account: true }
    }
    return { fund_flow: false, can_trade: true, can_edit_account: true }
  })

  async function login(username, password) {
    try {
      const r = await api.post('/api/v1/auth/login', { username, password })
      token.value = r.data.access_token
      localStorage.setItem('www_token', token.value)
      user.value = { user_id: r.data.user_id, username: r.data.username }
      await fetchUser()
      await fetchSubBanner()
      return true
    } catch { return false }
  }

  async function fetchUser() {
    try {
      const r = await api.get('/api/v1/users/me')
      user.value = r.data
    } catch {}
  }

  async function fetchSubBanner() {
    try {
      const r = await api.get('/api/v1/me/subaccount')
      subBanner.value = r.data
    } catch { subBanner.value = null }
  }

  function logout() {
    token.value = null; user.value = null; subBanner.value = null
    localStorage.removeItem('www_token')
  }

  if (token.value && !user.value) {
    fetchUser()
    fetchSubBanner()
  }

  return { token, user, subBanner, isAuthenticated, isSubAccount, viewCaps, login, logout, fetchUser, fetchSubBanner }
})
