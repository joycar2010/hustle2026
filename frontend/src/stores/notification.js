import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

export const useNotificationStore = defineStore('notification', () => {
  const alerts = ref([])
  const alertSettings = ref(null)
  const activePopup = ref(null)
  const audioContext = ref(null)
  const isAudioPlaying = ref(false)
  const systemAlerts = ref([])
  const riskAlerts = ref([]) // Risk alerts from Risk.vue

  // Alert switches with localStorage persistence
  const alertSoundEnabled = ref(localStorage.getItem('alertSoundEnabled') !== 'false')
  const singleLegAlertEnabled = ref(localStorage.getItem('singleLegAlertEnabled') !== 'false')

  // Toggle alert sound
  function toggleAlertSound(enabled) {
    alertSoundEnabled.value = enabled
    localStorage.setItem('alertSoundEnabled', enabled)
  }

  // Toggle single-leg alert
  function toggleSingleLegAlert(enabled) {
    singleLegAlertEnabled.value = enabled
    localStorage.setItem('singleLegAlertEnabled', enabled)
  }

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

  // Check single-leg trade alert
  function checkSingleLegAlert(data) {
    // Check if single-leg alert is enabled
    if (!singleLegAlertEnabled.value) return

    const alert = {
      id: Date.now() + '_single_leg',
      type: 'single_leg_alert',
      level: 'critical',
      title: data.title || '单腿交易警告',
      message: data.message,
      timestamp: data.timestamp || new Date().toISOString(),
      details: {
        strategy_type: data.strategy_type,
        action: data.action,
        binance_filled: data.binance_filled,
        bybit_filled: data.bybit_filled,
        unfilled_qty: data.unfilled_qty
      }
    }
    alerts.value.push(alert)
    triggerPopup(alert)
  }

  // Trigger popup notification
  function triggerPopup(alert) {
    activePopup.value = alert
    playAlertSound(alert)
  }

  // Play alert sound based on alert type
  async function playAlertSound(alert) {
    // Check if alert sound is enabled
    if (!alertSoundEnabled.value) return
    if (isAudioPlaying.value) return
    if (!alertSettings.value) return

    isAudioPlaying.value = true

    try {
      // Determine which sound file and repeat count to use based on alert type
      let soundFile = null
      let repeatCount = 3

      // Map alert types to sound settings
      if (alert.type.includes('single_leg')) {
        // Single-leg trading alerts
        soundFile = alertSettings.value.singleLegAlertSound
        repeatCount = alertSettings.value.singleLegAlertRepeatCount || 3
      } else if (alert.type.includes('forward') || alert.type.includes('reverse')) {
        // Spread alerts (forward_open, forward_close, reverse_open, reverse_close)
        soundFile = alertSettings.value.spreadAlertSound
        repeatCount = alertSettings.value.spreadAlertRepeatCount || 3
      } else if (alert.type.includes('asset')) {
        // Net asset alerts (binance_asset, bybit_asset, total_asset)
        soundFile = alertSettings.value.netAssetAlertSound
        repeatCount = alertSettings.value.netAssetAlertRepeatCount || 3
      } else if (alert.type.includes('mt5')) {
        // MT5 lag alerts
        soundFile = alertSettings.value.mt5AlertSound
        repeatCount = alertSettings.value.mt5AlertRepeatCount || 3
      } else if (alert.type.includes('liquidation')) {
        // Liquidation alerts
        soundFile = alertSettings.value.liquidationAlertSound
        repeatCount = alertSettings.value.liquidationAlertRepeatCount || 3
      }

      // If no custom sound file is set, use default
      if (!soundFile) {
        soundFile = '/sounds/hello-moto.mp3'
      }

      // Construct full URL for uploaded sound files
      // Use environment variable for API base URL
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://13.115.21.77:8000'
      const soundUrl = soundFile.startsWith('/uploads/')
        ? `${apiBaseUrl}${soundFile}`
        : soundFile

      console.log('Playing alert sound:', soundUrl)

      // Play the sound file the specified number of times
      for (let i = 0; i < repeatCount; i++) {
        try {
          // Create a new Audio instance for each play to avoid conflicts
          const audio = new Audio(soundUrl)

          // Wait for audio to be ready
          await new Promise((resolve, reject) => {
            audio.addEventListener('canplaythrough', resolve, { once: true })
            audio.addEventListener('error', reject, { once: true })
            audio.load()
          })

          // Play and wait for completion
          await new Promise((resolve, reject) => {
            audio.addEventListener('ended', resolve, { once: true })
            audio.addEventListener('error', reject, { once: true })
            audio.play().catch(reject)
          })
        } catch (audioError) {
          // Fallback to Web Audio API if file not found or play failed
          console.log('Audio file error, using Web Audio API:', audioError.message)
          await playHelloMotoTone()
        }

        // Pause between repetitions
        if (i < repeatCount - 1) {
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

  // Update system alerts from account data
  function updateSystemAlerts(data) {
    const newAlerts = []

    if (data.summary) {
      // Net value alert
      newAlerts.push({
        id: 1,
        type: 'warning',
        message: '账户净值提醒',
        value: `当前净值: $${formatNumber(data.summary.net_assets || 0)}`
      })

      // Risk status
      const riskRatio = data.summary.risk_ratio || 0
      if (riskRatio > 60) {
        newAlerts.push({
          id: 2,
          type: 'danger',
          message: '风险率过高',
          value: `当前风险率: ${riskRatio.toFixed(2)}%`
        })
      } else {
        newAlerts.push({
          id: 2,
          type: 'success',
          message: '风控状态',
          value: '正常运行'
        })
      }

      // Position count
      if (data.summary.position_count > 0) {
        newAlerts.push({
          id: 3,
          type: 'info',
          message: '持仓提醒',
          value: `当前持仓: ${data.summary.position_count} 个`
        })
      }
    }

    systemAlerts.value = newAlerts
  }

  // Helper function to format numbers
  function formatNumber(num) {
    return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  // Handle risk alert from WebSocket
  function handleRiskAlert(alertData) {
    const newAlert = {
      id: Date.now(),
      type: alertData.alert_type || 'risk_alert',
      level: alertData.level || 'warning',
      title: alertData.title || '风险警报',
      message: alertData.message,
      timestamp: alertData.timestamp || new Date().toISOString()
    }

    // Add to alerts list
    alerts.value.push(newAlert)

    // Add to risk alerts list (keep last 10)
    riskAlerts.value = [newAlert, ...riskAlerts.value].slice(0, 10)

    // Trigger popup and sound for all risk alerts
    triggerPopup(newAlert)
  }

  // Dismiss risk alert
  function dismissRiskAlert(id) {
    riskAlerts.value = riskAlerts.value.filter(a => a.id !== id)
  }

  // Show strategy notification (success/error/info)
  function showStrategyNotification(message, type = 'info') {
    const levelMap = {
      success: 'info',
      error: 'critical',
      warning: 'warning',
      info: 'info'
    }

    const alert = {
      id: Date.now() + '_strategy',
      type: 'strategy_notification',
      level: levelMap[type] || 'info',
      title: type === 'error' ? '策略执行失败' : type === 'success' ? '策略执行成功' : '策略通知',
      message: message,
      timestamp: new Date().toISOString()
    }

    alerts.value.push(alert)

    // Trigger popup for errors and important messages
    if (type === 'error' || type === 'warning') {
      triggerPopup(alert)
    }

    // Auto-dismiss after 5 seconds for success/info messages
    if (type === 'success' || type === 'info') {
      setTimeout(() => {
        dismissAlert(alert.id)
      }, 5000)
    }
  }

  return {
    alerts,
    alertSettings,
    activePopup,
    isAudioPlaying,
    alertSoundEnabled,
    singleLegAlertEnabled,
    systemAlerts,
    riskAlerts,
    loadAlertSettings,
    checkMarketAlerts,
    checkAccountAlerts,
    checkMT5LagAlert,
    checkSingleLegAlert,
    dismissAlert,
    dismissPopup,
    toggleAlertSound,
    toggleSingleLegAlert,
    updateSystemAlerts,
    handleRiskAlert,
    dismissRiskAlert,
    showStrategyNotification
  }
})
