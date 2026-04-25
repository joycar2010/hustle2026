// Global target context store — shared across all pages
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '@/api'

export const useTargetStore = defineStore('target', () => {
  const selectedTargetId = ref(null)
  const targets = ref([])
  const comparison = ref([])
  const loading = ref(false)
  const alerts = ref({ items: [], unacked_count: 0, by_level: {} })

  const selectedTarget = computed(() =>
    comparison.value.find(t => t.target_id === selectedTargetId.value) || null
  )

  function select(tid) {
    selectedTargetId.value = tid
  }

  async function loadTargets() {
    try {
      const r = await api.get('/api/v1/agent/scope/targets')
      targets.value = r.data?.items?.filter(t => t.enabled) || []
    } catch {}
  }

  async function loadComparison() {
    loading.value = true
    try {
      const r = await api.get('/api/v1/agent/targets/comparison')
      comparison.value = r.data?.items || []
    } catch { /* fallback: keep existing */ }
    finally { loading.value = false }
  }

  async function loadAlerts() {
    try {
      const r = await api.get('/api/v1/agent/alerts/active')
      alerts.value = r.data || { items: [], unacked_count: 0, by_level: {} }
    } catch {}
  }

  async function refresh() {
    await Promise.all([loadTargets(), loadComparison(), loadAlerts()])
  }

  return {
    selectedTargetId, targets, comparison, loading, alerts,
    selectedTarget, select, loadTargets, loadComparison, loadAlerts, refresh,
  }
})
