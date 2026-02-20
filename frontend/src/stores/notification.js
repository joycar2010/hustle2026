import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

export const useNotificationStore = defineStore('notification', () => {
  const alerts = ref([])
  const alertSettings = ref(null)
  const activePopup = ref(null)
  const audioContext = ref(null)
  const isAudioPlaying = ref(false)

  // Load alert settings from backend
  async function loadAlertSettings() {
    try {
      const response = await api.get('/api/v1/risk/alert-settings')
      if (response.data) {
        alertSettings.value = response.data
      }
    } catch (error) {
      console.error('Failed to load alert settings:', error)
    }
  }

  // Check market data against alert thresholds
  function checkMarketAlerts(marketData) {
    if (!alertSettings.value || !marketData) return

    const newAlerts = []

    // Check forward spread (Long Binance)
    if (marketData.forward_spread &&
        Math.abs(marketData.forward_spread) >= alertSettings.value.forwardOpenPrice) {
      newAlerts.push({
        id: Date.now() + '_forward_open',
        type: 'forward_open',
        level: 'warning',
        title: '正向套利开仓机会',
        message: `当前点差: ${marketData.forward_spread.toFixed(2)} USDT，达到开仓阈值 ${alertSettings.value.forwardOpenPrice} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    if (marketData.forward_spread &&
        Math.abs(marketData.forward_spread) <= alertSettings.value.forwardClosePrice) {
      newAlerts.push({
        id: Date.now() + '_forward_close',
        type: 'forward_close',
        level: 'info',
        title: '正向套利平仓机会',
        message: `当前点差: ${marketData.forward_spread.toFixed(2)} USDT，达到平仓阈值 ${alertSettings.value.forwardClosePrice} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    // Check reverse spread (Long Bybit)
    if (marketData.reverse_spread &&
        Math.abs(marketData.reverse_spread) >= alertSettings.value.reverseOpenPrice) {
      newAlerts.push({
        id: Date.now() + '_reverse_open',
        type: 'reverse_open',
        level: 'warning',
        title: '反向套利开仓机会',
        message: `当前点差: ${marketData.reverse_spread.toFixed(2)} USDT，达到开仓阈值 ${alertSettings.value.reverseOpenPrice} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    if (marketData.reverse_spread &&
        Math.abs(marketData.reverse_spread) <= alertSettings.value.reverseClosePrice) {
      newAlerts.push({
        id: Date.now() + '_reverse_close',
        type: 'reverse_close',
        level: 'info',
        title: '反向套利平仓机会',
        message: `当前点差: ${marketData.reverse_spread.toFixed(2)} USDT，达到平仓阈值 ${alertSettings.value.reverseClosePrice} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    // Add new alerts and trigger popup
    if (newAlerts.length > 0) {
      alerts.value.push(...newAlerts)
      triggerPopup(newAlerts[0])
    }
  }

  // Check account data against alert thresholds
  function checkAccountAlerts(accountData) {
    if (!alertSettings.value || !accountData) return

    const newAlerts = []

    // Check Binance net asset
    if (accountData.binance_net_asset &&
        accountData.binance_net_asset <= alertSettings.value.binanceNetAsset) {
      newAlerts.push({
        id: Date.now() + '_binance_asset',
        type: 'binance_asset',
        level: 'critical',
        title: 'Binance净资产预警',
        message: `当前净资产: ${accountData.binance_net_asset.toFixed(2)} USDT，低于阈值 ${alertSettings.value.binanceNetAsset} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    // Check Bybit MT5 net asset
    if (accountData.bybit_mt5_net_asset &&
        accountData.bybit_mt5_net_asset <= alertSettings.value.bybitMT5NetAsset) {
      newAlerts.push({
        id: Date.now() + '_bybit_asset',
        type: 'bybit_asset',
        level: 'critical',
        title: 'Bybit MT5净资产预警',
        message: `当前净资产: ${accountData.bybit_mt5_net_asset.toFixed(2)} USDT，低于阈值 ${alertSettings.value.bybitMT5NetAsset} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    // Check total net asset
    if (accountData.total_net_asset &&
        accountData.total_net_asset <= alertSettings.value.totalNetAsset) {
      newAlerts.push({
        id: Date.now() + '_total_asset',
        type: 'total_asset',
        level: 'critical',
        title: '总资产预警',
        message: `当前总资产: ${accountData.total_net_asset.toFixed(2)} USDT，低于阈值 ${alertSettings.value.totalNetAsset} USDT`,
        timestamp: new Date().toISOString()
      })
    }

    // Add new alerts and trigger popup
    if (newAlerts.length > 0) {
      alerts.value.push(...newAlerts)
      triggerPopup(newAlerts[0])
    }
  }

  // Check MT5 lag count
  function checkMT5LagAlert(lagCount) {
    if (!alertSettings.value || lagCount === undefined) return

    if (lagCount >= alertSettings.value.mt5LagCount) {
      const alert = {
        id: Date.now() + '_mt5_lag',
        type: 'mt5_lag',
        level: 'warning',
        title: 'MT5卡顿预警',
        message: `当前卡顿次数: ${lagCount}，达到阈值 ${alertSettings.value.mt5LagCount}`,
        timestamp: new Date().toISOString()
      }
      alerts.value.push(alert)
      triggerPopup(alert)
    }
  }

  // Trigger popup notification
  function triggerPopup(alert) {
    activePopup.value = alert
    playAlertSound()
  }

  // Play "Hello Moto" ringtone 3 times for 10 seconds
  async function playAlertSound() {
    if (isAudioPlaying.value) return
    isAudioPlaying.value = true

    try {
      // Try to play audio file first, fallback to Web Audio API
      const audio = new Audio('/sounds/hello-moto.mp3')

      // Play 3 times
      for (let i = 0; i < 3; i++) {
        try {
          audio.currentTime = 0
          await audio.play()
          await new Promise(resolve => setTimeout(resolve, 10000)) // 10 seconds
          audio.pause()
        } catch (audioError) {
          // Fallback to Web Audio API if file not found
          console.log('Audio file not found, using Web Audio API')
          await playHelloMotoTone()
        }

        if (i < 2) {
          await new Promise(resolve => setTimeout(resolve, 500)) // 0.5s pause between plays
        }
      }
    } catch (error) {
      console.error('Failed to play alert sound:', error)
    } finally {
      isAudioPlaying.value = false
    }
  }

  // Generate "Hello Moto" tone using Web Audio API
  function playHelloMotoTone() {
    return new Promise((resolve) => {
      // Create audio context if not exists
      if (!audioContext.value) {
        audioContext.value = new (window.AudioContext || window.webkitAudioContext)()
      }

      const ctx = audioContext.value
      const duration = 10 // 10 seconds

      // Create oscillator for the tone
      const oscillator = ctx.createOscillator()
      const gainNode = ctx.createGain()

      oscillator.connect(gainNode)
      gainNode.connect(ctx.destination)

      // Set frequency (approximate "Hello Moto" melody)
      oscillator.frequency.setValueAtTime(523.25, ctx.currentTime) // C5
      oscillator.frequency.setValueAtTime(587.33, ctx.currentTime + 0.3) // D5
      oscillator.frequency.setValueAtTime(659.25, ctx.currentTime + 0.6) // E5
      oscillator.frequency.setValueAtTime(523.25, ctx.currentTime + 0.9) // C5

      // Set volume envelope
      gainNode.gain.setValueAtTime(0.3, ctx.currentTime)
      gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + duration)

      oscillator.start(ctx.currentTime)
      oscillator.stop(ctx.currentTime + duration)

      oscillator.onended = () => resolve()
    })
  }

  // Dismiss alert
  function dismissAlert(alertId) {
    alerts.value = alerts.value.filter(a => a.id !== alertId)
    if (activePopup.value && activePopup.value.id === alertId) {
      activePopup.value = null
    }
  }

  // Dismiss popup
  function dismissPopup() {
    activePopup.value = null
  }

  return {
    alerts,
    alertSettings,
    activePopup,
    isAudioPlaying,
    loadAlertSettings,
    checkMarketAlerts,
    checkAccountAlerts,
    checkMT5LagAlert,
    dismissAlert,
    dismissPopup
  }
})
