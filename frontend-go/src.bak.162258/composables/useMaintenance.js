// Shared maintenance state composable for frontend-go.
// All trading buttons should consult `maintenanceActive` and disable themselves.
import { computed } from 'vue'
import { useWsStream } from '@/stores/wsStream.js'
import api from '@/services/api.js'

let _initialized = false

export function useMaintenance() {
  const ws = useWsStream()
  if (!_initialized) {
    _initialized = true
    ws.subscribe('site.status')
    api.get('/api/v1/site-status')
      .then(r => { ws.channels['site.status'] = r.data })
      .catch(() => {})
  }
  const siteStatus = computed(() => ws.channels['site.status'] || { announcements: [], maintenance: {} })
  const maintenanceActive = computed(() => !!siteStatus.value.maintenance?.is_active)
  const maintenanceReason = computed(() => siteStatus.value.maintenance?.reason || '')
  const maintenanceResume = computed(() => siteStatus.value.maintenance?.scheduled_resume_at || null)
  return { siteStatus, maintenanceActive, maintenanceReason, maintenanceResume }
}
