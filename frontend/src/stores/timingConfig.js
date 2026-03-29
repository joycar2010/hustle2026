import { defineStore } from 'pinia'
import api from '@/services/api'

export const useTimingConfigStore = defineStore('timingConfig', {
  state: () => ({
    configs: [],
    effectiveConfigs: {},
    loading: false,
    error: null
  }),

  getters: {
    getConfigByLevel: (state) => (level, strategyType = null) => {
      return state.configs.find(c =>
        c.config_level === level &&
        (strategyType ? c.strategy_type === strategyType : true)
      )
    },

    globalConfig: (state) => {
      return state.configs.find(c => c.config_level === 'global')
    },

    strategyTypeConfigs: (state) => {
      return state.configs.filter(c => c.config_level === 'strategy_type')
    }
  },

  actions: {
    async fetchConfigs() {
      this.loading = true
      this.error = null
      try {
        const response = await api.get('/api/v1/timing-configs')
        this.configs = response.data
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取配置失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async fetchEffectiveConfig(strategyType, instanceId = null) {
      this.loading = true
      this.error = null
      try {
        const params = instanceId ? { instance_id: instanceId } : {}
        const response = await api.get(`/api/v1/timing-configs/effective/${strategyType}`, { params })
        this.effectiveConfigs[strategyType] = response.data
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取有效配置失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async getConfigById(configId) {
      this.loading = true
      this.error = null
      try {
        const response = await api.get(`/api/v1/timing-configs/${configId}`)
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取配置失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async createConfig(configData) {
      this.loading = true
      this.error = null
      try {
        const response = await api.post('/api/v1/timing-configs', configData)
        await this.fetchConfigs() // Refresh list
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '创建配置失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async updateConfig(configId, configData) {
      this.loading = true
      this.error = null
      try {
        const response = await api.put(`/api/v1/timing-configs/${configId}`, configData)
        await this.fetchConfigs() // Refresh list
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '更新配置失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async deleteConfig(configId) {
      this.loading = true
      this.error = null
      try {
        await api.delete(`/api/v1/timing-configs/${configId}`)
        await this.fetchConfigs() // Refresh list
        return true
      } catch (error) {
        this.error = error.response?.data?.detail || '删除配置失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async reloadConfigs() {
      this.loading = true
      this.error = null
      try {
        const response = await api.post('/api/v1/timing-configs/reload')
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '触发重载失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async fetchConfigHistory(strategyType) {
      this.loading = true
      this.error = null
      try {
        const response = await api.get(`/api/v1/timing-configs/history/${strategyType}`)
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取配置历史失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async fetchCustomTemplates(strategyType) {
      this.loading = true
      this.error = null
      try {
        const response = await api.get(`/api/v1/timing-configs/templates/${strategyType}`)
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '获取自定义模板失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async createCustomTemplate(templateData) {
      this.loading = true
      this.error = null
      try {
        const response = await api.post('/api/v1/timing-configs/templates', templateData)
        return response.data
      } catch (error) {
        this.error = error.response?.data?.detail || '创建自定义模板失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    async deleteCustomTemplate(templateId) {
      this.loading = true
      this.error = null
      try {
        await api.delete(`/api/v1/timing-configs/templates/${templateId}`)
        return true
      } catch (error) {
        this.error = error.response?.data?.detail || '删除自定义模板失败'
        throw error
      } finally {
        this.loading = false
      }
    }
  }
})
