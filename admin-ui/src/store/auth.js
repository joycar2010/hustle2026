import { defineStore } from 'pinia'
import { getTok, setTok, clearTok } from '../api'

export const useAuth = defineStore('auth', {
  state: () => ({ token: getTok(), role: '', name: '' }),
  getters: {
    authed: (s) => !!s.token,
    isOperator: (s) => ['OPERATOR', 'SUPER_ADMIN'].includes(s.role),
    isSuper: (s) => s.role === 'SUPER_ADMIN',
  },
  actions: {
    login(t) { setTok(t); this.token = getTok() },
    logout() { clearTok(); this.token = ''; this.role = '' },
    setMe(me) { if (me) { this.role = me.role; this.name = me.name } },
  },
})
