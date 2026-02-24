import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useSslStore = defineStore('ssl', () => {
  // State
  const certificates = ref([])
  const currentCertificate = ref(null)
  const certificateLogs = ref([])
  const loading = ref(false)
  const error = ref(null)

  // Computed
  const activeCertificates = computed(() =>
    certificates.value.filter(c => c.status === 'active')
  )
  const expiringSoonCertificates = computed(() =>
    certificates.value.filter(c => c.status === 'expiring_soon')
  )
  const expiredCertificates = computed(() =>
    certificates.value.filter(c => c.status === 'expired')
  )

  // Actions
  const fetchCertificates = async (filters = {}) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get('/api/v1/ssl/certificates', {
        params: filters
      })
      certificates.value = response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取证书列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchCertificateById = async (certId) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/ssl/certificates/${certId}`)
      currentCertificate.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取证书详情失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const uploadCertificate = async (certData) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.post('/api/v1/ssl/certificates', certData)
      certificates.value.push(response.data)
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '上传证书失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const deployCertificate = async (certId, deployData) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.post(
        `/api/v1/ssl/certificates/${certId}/deploy`,
        deployData
      )
      const cert = certificates.value.find(c => c.cert_id === certId)
      if (cert) {
        cert.is_deployed = true
        cert.status = 'active'
      }
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '部署证书失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const deleteCertificate = async (certId) => {
    loading.value = true
    error.value = null
    try {
      await axios.delete(`/api/v1/ssl/certificates/${certId}`)
      certificates.value = certificates.value.filter(c => c.cert_id !== certId)
    } catch (err) {
      error.value = err.response?.data?.detail || '删除证书失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const getCertificateStatus = async (certId) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/ssl/certificates/${certId}/status`)
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取证书状态失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchCertificateLogs = async (certId, limit = 50) => {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get(`/api/v1/ssl/certificates/${certId}/logs`, {
        params: { limit }
      })
      certificateLogs.value = response.data
      return response.data
    } catch (err) {
      error.value = err.response?.data?.detail || '获取证书日志失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    certificates,
    currentCertificate,
    certificateLogs,
    loading,
    error,
    activeCertificates,
    expiringSoonCertificates,
    expiredCertificates,
    fetchCertificates,
    fetchCertificateById,
    uploadCertificate,
    deployCertificate,
    deleteCertificate,
    getCertificateStatus,
    fetchCertificateLogs
  }
})
