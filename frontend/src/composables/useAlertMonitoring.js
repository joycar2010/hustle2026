import { onMounted, onUnmounted, watch } from 'vue'
import { useNotificationStore } from '@/stores/notification'
import { useMarketStore } from '@/stores/market'
import api from '@/services/api'

export function useAlertMonitoring() {
  const notificationStore = useNotificationStore()
  const marketStore = useMarketStore()

  let unwatchMarket = null
  let unwatchAccount = null
  let unwatchSingleLeg = null
  let unwatchMT5 = null
  let unwatchRiskAlert = null

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
      const response = await api.get('/api/v1/mt5/connection/status')
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

    // Connect to WebSocket if not already connected
    if (!marketStore.connected) {
      marketStore.connect()
    }

    // Watch for market_data WebSocket messages
    unwatchMarket = watch(() => marketStore.lastMessage, (message) => {
      if (message && message.type === 'market_data') {
        notificationStore.checkMarketAlerts(message.data)
      }
    })

    // Watch for account_balance WebSocket messages (backend broadcasts every 10s)
    unwatchAccount = watch(() => marketStore.lastMessage, (message) => {
      if (message && message.type === 'account_balance') {
        const accountData = {
          binance_net_asset: message.data.summary?.binance_net_asset || 0,
          bybit_mt5_net_asset: message.data.summary?.bybit_mt5_net_asset || 0,
          total_net_asset: message.data.summary?.total_assets || 0
        }
        notificationStore.checkAccountAlerts(accountData)

        // Check liquidation prices
        const liquidationData = {
          binance_account: message.data.accounts?.find(acc => acc.platform_id === 1),
          bybit_account: message.data.accounts?.find(acc => acc.platform_id === 2 && acc.is_mt5_account),
          binance_current_price: message.data.market?.binance_price,
          bybit_current_price: message.data.market?.bybit_price
        }
        notificationStore.checkLiquidationAlerts(liquidationData)
      }
    })

    // Watch for single_leg_alert WebSocket messages
    unwatchSingleLeg = watch(() => marketStore.lastMessage, (message) => {
      if (message && message.type === 'single_leg_alert') {
        notificationStore.checkSingleLegAlert(message.data)
      }
    })

    // Watch for MT5 connection status WebSocket messages (backend broadcasts every 30s)
    unwatchMT5 = watch(() => marketStore.lastMessage, (message) => {
      if (message && message.type === 'mt5_connection_status') {
        if (!message.data.healthy || message.data.connection_failures > 0) {
          notificationStore.checkMT5LagAlert(message.data.connection_failures)
        }
      }
    })

    // Watch for risk_alert WebSocket messages from backend notification services
    unwatchRiskAlert = watch(() => marketStore.lastMessage, (message) => {
      if (message && message.type === 'risk_alert') {
        // Handle risk alerts from backend (spread alerts, asset alerts, etc.)
        notificationStore.handleRiskAlert(message.data)
      }
    })

    // Initial checks
    checkMarketData()
    checkAccountData()
    checkMT5Status()
  }

  // Stop monitoring
  function stopMonitoring() {
    if (unwatchMarket) unwatchMarket()
    if (unwatchAccount) unwatchAccount()
    if (unwatchSingleLeg) unwatchSingleLeg()
    if (unwatchMT5) unwatchMT5()
    if (unwatchRiskAlert) unwatchRiskAlert()
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
