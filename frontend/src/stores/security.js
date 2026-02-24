import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useSecurityStore = defineStore('security', () => {
  // State
  const components = ref([])
  const currentComponent = ref(null)
  const componentLogs = ref([])
  const loading = ref(false)
  const error = ref(null)

  // Computed
  const enabledComponents = computed(() =>
    components.value.filter(c => c.is_enabled)
  )
  const disabledComponents = computed(() =>
    components.value.filter(c => !c.is_enabled)
  )

  // Actions
  const fetchComponents = async () => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get('/api/v1/security/components')
      components.value = response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取安全组件列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchComponentById = async (componentId) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/security/components/${componentId}`)
      currentComponent.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取组件详情失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const enableComponent = async (componentId) => {
    loading.value = true
    error.value = null
    try {
      await axios.post(`/api/v1/security/components/${componentId}/enable`)
      const component = components.value.find(c => c.component_id === componentId)
      if (component) {
        component.is_enabled = true
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '启用组件失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const disableComponent = async (componentId) => {
    loading.value = true
    error.value = null
    try {
      await axios.post(`/api/v1/security/components/${componentId}/disable`)
      const component = components.value.find(c => c.component_id === componentId)
      if (component) {
        component.is_enabled = false
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '禁用组件失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const updateComponentConfig = async (componentId, config) => {
    loading.value = true
    error.value = null
    try {
      await axios.put(`/api/v1/security/components/${componentId}/config`, {
        config
      })
      const component = components.value.find(c => c.component_id === componentId)
      if (component) {
        component.config = config
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '更新配置失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const getComponentStatus = async (componentId) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/security/components/${componentId}/status`)
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取组件状态失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchComponentLogs = async (componentId, limit = 50) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/security/components/${componentId}/logs`, {
        params: { limit }
      })
      componentLogs.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取组件日志失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    components,
    currentComponent,
    componentLogs,
    loading,
    error,
    enabledComponents,
    disabledComponents,
    fetchComponents,
    fetchComponentById,
    enableComponent,
    disableComponent,
    updateComponentConfig,
    getComponentStatus,
    fetchComponentLogs
  }
})
