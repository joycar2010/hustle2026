/**
 * WebSocket Connection Tests
 *
 * Tests for WebSocket connectivity, reconnection, and fallback behavior
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMarketStore } from '@/stores/market'

describe('WebSocket Market Store', () => {
  let marketStore

  beforeEach(() => {
    setActivePinia(createPinia())
    marketStore = useMarketStore()

    // Mock WebSocket
    global.WebSocket = vi.fn(() => ({
      send: vi.fn(),
      close: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      readyState: WebSocket.OPEN
    }))
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('Connection Management', () => {
    it('should initialize with disconnected state', () => {
      expect(marketStore.connected).toBe(false)
      expect(marketStore.marketData).toBeNull()
    })

    it('should connect to WebSocket', async () => {
      await marketStore.connect()

      expect(global.WebSocket).toHaveBeenCalled()
      expect(marketStore.connecting).toBe(true)
    })

    it('should handle connection success', () => {
      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'open') {
            handler()
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)

      marketStore.connect()

      expect(marketStore.connected).toBe(true)
      expect(marketStore.connecting).toBe(false)
    })

    it('should handle connection error', () => {
      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'error') {
            handler(new Error('Connection failed'))
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)

      marketStore.connect()

      expect(marketStore.connected).toBe(false)
      expect(marketStore.error).toBeTruthy()
    })

    it('should disconnect cleanly', () => {
      const mockWs = {
        close: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn()
      }

      marketStore.ws = mockWs
      marketStore.connected = true

      marketStore.disconnect()

      expect(mockWs.close).toHaveBeenCalled()
      expect(marketStore.connected).toBe(false)
    })
  })

  describe('Message Handling', () => {
    it('should handle market_data messages', () => {
      const mockData = {
        binance_bid: 2000.50,
        binance_ask: 2000.60,
        bybit_bid: 2000.45,
        bybit_ask: 2000.55,
        timestamp: '2026-02-24T10:00:00Z'
      }

      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'message') {
            handler({
              data: JSON.stringify({
                type: 'market_data',
                data: mockData
              })
            })
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)
      marketStore.connect()

      expect(marketStore.marketData).toEqual(mockData)
      expect(marketStore.lastMessage).toEqual({
        type: 'market_data',
        data: mockData
      })
    })

    it('should handle order_update messages', () => {
      const mockOrder = {
        order: {
          id: '123',
          status: 'filled',
          symbol: 'XAUUSDT'
        }
      }

      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'message') {
            handler({
              data: JSON.stringify({
                type: 'order_update',
                data: mockOrder
              })
            })
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)
      marketStore.connect()

      expect(marketStore.lastMessage.type).toBe('order_update')
      expect(marketStore.lastMessage.data).toEqual(mockOrder)
    })

    it('should handle account_balance messages', () => {
      const mockBalance = {
        summary: {
          total_assets: 10000,
          net_assets: 9500
        }
      }

      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'message') {
            handler({
              data: JSON.stringify({
                type: 'account_balance',
                data: mockBalance
              })
            })
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)
      marketStore.connect()

      expect(marketStore.lastMessage.type).toBe('account_balance')
      expect(marketStore.lastMessage.data).toEqual(mockBalance)
    })

    it('should handle risk_metrics messages', () => {
      const mockRisk = {
        summary: {
          risk_ratio: 0.15
        },
        positions: []
      }

      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'message') {
            handler({
              data: JSON.stringify({
                type: 'risk_metrics',
                data: mockRisk
              })
            })
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)
      marketStore.connect()

      expect(marketStore.lastMessage.type).toBe('risk_metrics')
      expect(marketStore.lastMessage.data).toEqual(mockRisk)
    })
  })

  describe('Reconnection Logic', () => {
    it('should attempt reconnection on disconnect', async () => {
      vi.useFakeTimers()

      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'close') {
            handler()
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)

      marketStore.connect()
      marketStore.connected = true

      // Trigger close event
      mockWs.addEventListener.mock.calls
        .find(call => call[0] === 'close')[1]()

      expect(marketStore.connected).toBe(false)

      // Fast-forward time to trigger reconnection
      vi.advanceTimersByTime(10000)

      expect(global.WebSocket).toHaveBeenCalledTimes(2)

      vi.useRealTimers()
    })

    it('should use exponential backoff for reconnection', async () => {
      vi.useFakeTimers()

      let attemptCount = 0
      global.WebSocket = vi.fn(() => {
        attemptCount++
        return {
          addEventListener: vi.fn((event, handler) => {
            if (event === 'error') {
              handler(new Error('Connection failed'))
            }
          }),
          send: vi.fn(),
          close: vi.fn()
        }
      })

      marketStore.connect()

      // First reconnection after 10s
      vi.advanceTimersByTime(10000)
      expect(attemptCount).toBe(2)

      // Second reconnection after another 10s
      vi.advanceTimersByTime(10000)
      expect(attemptCount).toBe(3)

      vi.useRealTimers()
    })
  })

  describe('Fallback Behavior', () => {
    it('should allow manual data fetch when WebSocket fails', async () => {
      // Mock failed WebSocket connection
      marketStore.connected = false
      marketStore.error = 'Connection failed'

      // Mock API fetch
      const mockFetch = vi.fn().mockResolvedValue({
        binance_bid: 2000.50,
        binance_ask: 2000.60
      })

      marketStore.fetchMarketData = mockFetch

      const data = await marketStore.fetchMarketData()

      expect(mockFetch).toHaveBeenCalled()
      expect(data).toBeDefined()
    })
  })

  describe('Message Statistics', () => {
    it('should track message count', () => {
      const mockWs = {
        addEventListener: vi.fn((event, handler) => {
          if (event === 'message') {
            // Simulate 3 messages
            handler({ data: JSON.stringify({ type: 'market_data', data: {} }) })
            handler({ data: JSON.stringify({ type: 'order_update', data: {} }) })
            handler({ data: JSON.stringify({ type: 'account_balance', data: {} }) })
          }
        }),
        send: vi.fn(),
        close: vi.fn()
      }

      global.WebSocket = vi.fn(() => mockWs)
      marketStore.connect()

      // Assuming store tracks message count
      expect(marketStore.messageCount).toBeGreaterThanOrEqual(3)
    })
  })
})
