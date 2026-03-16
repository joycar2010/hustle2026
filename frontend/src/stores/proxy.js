import { defineStore } from 'pinia'
import axios from 'axios'

export const useProxyStore = defineStore('proxy', {
  state: () => ({
    proxies: [],
    qingguoBalance: null,
    loading: false,
    error: null
  }),

  getters: {
    activeProxies: (state) => state.proxies.filter(p => p.status === 'active'),
    localProxies: (state) => state.proxies.filter(p => p.provider === 'local'),
    qingguoProxies: (state) => state.proxies.filter(p => p.provider === 'qingguo'),
    proxyById: (state) => (id) => state.proxies.find(p => p.id === id)
  },

  actions: {
    async fetchProxies() {
      this.loading = true
      this.error = null
      try {
        const response = await axios.get('/api/v1/proxies')
        this.proxies = response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取代理列表失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async fetchQingguoBalance() {
      try {
        const response = await axios.get('/api/v1/proxies/qingguo/balance')
        this.qingguoBalance = response.data
        return response.data
      } catch (error) {
        console.error('获取青果余额失败:', error)
        throw error
      }
    },

    async createLocalProxy(data) {
      this.loading = true
      this.error = null
      try {
        const response = await axios.post('/api/v1/proxies/local', data)
        await this.fetchProxies()
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '创建本地代理失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async fetchFromQingguo(params) {
      this.loading = true
      this.error = null
      try {
        const response = await axios.post('/api/v1/proxies/fetch-from-qingguo', params)
        await this.fetchProxies()
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '从青果获取代理失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async updateProxy(id, data) {
      this.loading = true
      this.error = null
      try {
        const response = await axios.put(`/api/v1/proxies/${id}`, data)
        await this.fetchProxies()
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '更新代理失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async deleteProxy(id) {
      this.loading = true
      this.error = null
      try {
        await axios.delete(`/api/v1/proxies/${id}`)
        await this.fetchProxies()
      } catch (error) {
        this.error = error.response?.data?.detail || '删除代理失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async checkProxyHealth(id) {
      try {
        const response = await axios.post(`/api/v1/proxies/${id}/health-check`)
        await this.fetchProxies()
        return response.data
      } catch (error) {
        console.error('检查代理健康度失败:', error)
        throw error
      }
    },

    async bindProxyToAccount(accountId, platformId, proxyId) {
      try {
        const response = await axios.post('/api/v1/accounts/proxy/config', {
          account_id: accountId,
          platform_id: platformId,
          proxy_id: proxyId
        })
        return response.data
      } catch (error) {
        console.error('绑定代理失败:', error)
        throw error
      }
    },

    async unbindProxyFromAccount(accountId, platformId) {
      try {
        const response = await axios.delete('/api/v1/accounts/proxy/config', {
          data: {
            account_id: accountId,
            platform_id: platformId
          }
        })
        return response.data
      } catch (error) {
        console.error('解绑代理失败:', error)
        throw error
      }
    },

    async getAccountProxy(accountId, platformId) {
      try {
        const response = await axios.get(`/api/v1/accounts/${accountId}/proxy/${platformId}`)
        return response.data
      } catch (error) {
        console.error('获取账户代理失败:', error)
        throw error
      }
    }
  }
})
