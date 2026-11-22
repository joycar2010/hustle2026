import { defineStore } from 'pinia'
import api from '@/services/api'

export const useMT5ClientStore = defineStore('mt5Client', {
  state: () => ({
    clients: [],
    loading: false,
    error: null,
    currentAccountId: null
  }),

  getters: {
    getClientsByAccount: (state) => (accountId) => {
      return state.clients.filter(c => c.account_id === accountId)
    },

    getConnectedCount: (state) => (accountId) => {
      return state.clients.filter(
        c => c.account_id === accountId && c.connection_status === 'connected'
      ).length
    },

    getTotalCount: (state) => (accountId) => {
      return state.clients.filter(c => c.account_id === accountId).length
    }
  },

  actions: {
    async fetchClients(accountId) {
      this.loading = true
      this.error = null
      this.currentAccountId = accountId

      try {
        const response = await api.get(`/api/v1/accounts/${accountId}/mt5-clients`)
        this.clients = response.data
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取MT5客户端列表失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async createClient(accountId, clientData) {
      this.loading = true
      this.error = null

      console.log('=== MT5 Client Store: createClient ===')
      console.log('Account ID:', accountId)
      console.log('Client Data:', clientData)
      console.log('Client Data JSON:', JSON.stringify(clientData, null, 2))
      console.log('API URL:', `/api/v1/accounts/${accountId}/mt5-clients`)

      try {
        const response = await api.post(
          `/api/v1/accounts/${accountId}/mt5-clients`,
          clientData
        )
        console.log('Create client response:', response)
        this.clients.push(response.data)
        return response.data
      } catch (error) {
        console.error('Create client error:', error)
        console.error('Error response:', error.response)
        console.error('Error status:', error.response?.status)
        console.error('Error data:', error.response?.data)
        console.error('Error detail:', error.response?.data?.detail)
        console.error('Full error object:', JSON.stringify(error.response?.data, null, 2))
        this.error = error.response?.data?.detail || '创建MT5客户端失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async updateClient(clientId, clientData) {
      this.loading = true
      this.error = null

      try {
        const response = await api.put(
          `/api/v1/mt5-clients/${clientId}`,
          clientData
        )
        const index = this.clients.findIndex(c => c.client_id === clientId)
        if (index !== -1) {
          this.clients[index] = response.data
        }
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '更新MT5客户端失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async deleteClient(clientId) {
      this.loading = true
      this.error = null

      try {
        await api.delete(`/api/v1/mt5-clients/${clientId}`)
        this.clients = this.clients.filter(c => c.client_id !== clientId)
      } catch (error) {
        this.error = error.response?.data?.detail || '删除MT5客户端失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async connectClient(clientId) {
      this.loading = true
      this.error = null

      try {
        const response = await api.post(`/api/v1/mt5-clients/${clientId}/connect`)
        const index = this.clients.findIndex(c => c.client_id === clientId)
        if (index !== -1) {
          this.clients[index] = response.data
        }
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '连接MT5客户端失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async disconnectClient(clientId) {
      this.loading = true
      this.error = null

      try {
        const response = await api.post(`/api/v1/mt5-clients/${clientId}/disconnect`)
        const index = this.clients.findIndex(c => c.client_id === clientId)
        if (index !== -1) {
          this.clients[index] = response.data
        }
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '断开MT5客户端失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async detectMT5Installations() {
      try {
        const response = await api.get('/api/v1/mt5/detect-installations')
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '检测MT5安装路径失败'
        throw error
      }
    }
  }
})

