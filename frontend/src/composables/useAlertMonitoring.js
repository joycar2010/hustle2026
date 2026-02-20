import { onMounted, onUnmounted } from 'vue'
import { useNotificationStore } from '@/stores/notification'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

export function useAlertMonitoring() {
  const notificationStore = useNotificationStore()
  const marketStore = useMarketStore()

  let marketCheckInterval = null
  let accountCheckInterval = null
  let mt5CheckInterval = null

  // Monitor market data for spread alerts
  async function checkMarketData() {
    try {
      const data = await marketStore.fetchMarketData()
      if (data) {
        notificationStore.checkMarketAlerts(data)
      }
    } catch (error) {
      console.error('Failed to check market data:', error)
    }
  }

  // Monitor account data for asset alerts
  async function checkAccountData() {
    try {
      const response = await api.get('/api/v1/accounts/dashboard/aggregated')
      if (response.data) {
        const accountData = {
          binance_net_asset: response.data.binance?.net_asset || 0,
          bybit_mt5_net_asset: response.data.bybit_mt5?.net_asset || 0,
          total_net_asset: (response.data.binance?.net_asset || 0) + (response.data.bybit_mt5?.net_asset || 0)
        }
        notificationStore.checkAccountAlerts(accountData)
      }
    } catch (error) {
      console.error('Failed to check account data:', error)
    }
  }

  // Monitor MT5 connection status
  async function checkMT5Status() {
    try {
      const response = await api.get('/api/v1/market/connection/status')
      if (response.data && response.data.mt5) {
        // Check if connection is unhealthy or has failures
        if (!response.data.mt5.healthy || response.data.mt5.connection_failures > 0) {
          notificationStore.checkMT5LagAlert(response.data.mt5.connection_failures)
        }
      }
    } catch (error) {
      console.error('Failed to check MT5 status:', error)
    }
  }

  // Start monitoring
  function startMonitoring() {
    // Load alert settings first
    notificationStore.loadAlertSettings()

    // Check market data every 5 seconds
    marketCheckInterval = setInterval(checkMarketData, 5000)

    // Check account data every 10 seconds
    accountCheckInterval = setInterval(checkAccountData, 10000)

    // Check MT5 status every 15 seconds
    mt5CheckInterval = setInterval(checkMT5Status, 15000)

    // Initial checks
    checkMarketData()
    checkAccountData()
    checkMT5Status()
  }

  // Stop monitoring
  function stopMonitoring() {
    if (marketCheckInterval) clearInterval(marketCheckInterval)
    if (accountCheckInterval) clearInterval(accountCheckInterval)
    if (mt5CheckInterval) clearInterval(mt5CheckInterval)
  }

  // Auto-start on mount and cleanup on unmount
  onMounted(() => {
    startMonitoring()
  })

  onUnmounted(() => {
    stopMonitoring()
  })

  return {
    startMonitoring,
    stopMonitoring
  }
}
