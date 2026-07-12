// composable for www maintenance state
import { computed } from 'vue'
import { useWsStream } from '@/stores/wsStream.js'
import api from '@/services/api.js'

let _initialized = false

export function useMaintenance() {
  const ws = useWsStream()
  if (!_initialized) {
    _initialized = true
    ws.subscribe('site.status')
    api.get('/api/v1/site-status').then(r => { ws.channels['site.status'] = r.data }).catch(() => {})
  }
  const site = computed(() => ws.channels['site.status'] || { announcements: [], maintenance: {} })
  const maintenanceActive = computed(() => !!site.value.maintenance?.is_active)
  const maintenanceReason = computed(() => site.value.maintenance?.reason || '')
  const maintenanceResume = computed(() => site.value.maintenance?.scheduled_resume_at || null)
  return { site, maintenanceActive, maintenanceReason, maintenanceResume }
}
