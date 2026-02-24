# WebSocket Regression Prevention Guide

**Date**: 2026-02-24
**Purpose**: Prevent reintroduction of HTTP polling patterns after WebSocket transformation

## Overview

This project has completed a comprehensive WebSocket transformation, reducing HTTP requests by 93% (240+ → 16/min) and improving data latency by 10x (1000ms → <100ms). This guide ensures these improvements are maintained.

## Automated Checks

### 1. Pre-commit Hook ✓

**Location**: `.git/hooks/pre-commit`

**What it does**:
- Scans staged Vue/JS/TS files for HTTP polling patterns
- Detects `setInterval` with API calls
- Warns about short interval timers with network requests
- Provides guidance on using WebSocket instead
- Allows bypass with `--no-verify` for intentional cases

**Installation**: Already installed and executable

**Test it**:
```bash
# Create a test file with polling
echo "setInterval(() => api.get('/test'), 5000)" > test.js
git add test.js
git commit -m "test"
# Should trigger warning
rm test.js
```

### 2. CI/CD Integration (Recommended)

Add to your CI/CD pipeline:

```yaml
# .github/workflows/polling-check.yml
name: Check for HTTP Polling

on: [pull_request]

jobs:
  check-polling:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Check for polling patterns
        run: |
          if grep -r "setInterval.*fetch\|setInterval.*api\.\|setInterval.*axios\." frontend/src --include="*.vue" --include="*.js"; then
            echo "❌ HTTP polling pattern detected"
            exit 1
          fi
          echo "✅ No polling patterns found"
```

## Allowed Patterns

### ✅ UI-Only Timers (No Network Calls)

```javascript
// Timestamp updates
setInterval(updateLastUpdated, 1000)

// Animations
setInterval(updateAnimation, 100)

// Lag detection
setInterval(() => {
  if (Date.now() - lastUpdateTime > 2000) {
    lagCount.value++
  }
}, 2000)

// Uptime calculation
setInterval(() => {
  uptime.value = Date.now() - connectedAt
}, 1000)
```

### ✅ File-Based Operations

```javascript
// Log file refresh (not network)
setInterval(refreshLogs, 5000)
```

### ✅ Hybrid Mode (Reduced Polling + WebSocket)

```javascript
// Fallback polling at 30s+ intervals
onMounted(() => {
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // WebSocket for real-time updates
  watch(() => marketStore.lastMessage, (message) => {
    if (message?.type === 'order_update') {
      handleOrderUpdate(message.data)
    }
  })

  // Reduced polling as fallback (30s+)
  updateInterval = setInterval(fetchData, 30000)
})
```

## Prohibited Patterns

### ❌ High-Frequency HTTP Polling

```javascript
// BAD: Polling every 1-5 seconds
setInterval(() => {
  api.get('/api/v1/market/data')
}, 1000)

// GOOD: Use WebSocket instead
watch(() => marketStore.marketData, (newData) => {
  // Handle real-time updates
})
```

### ❌ Direct API Polling Without WebSocket

```javascript
// BAD: Only polling, no WebSocket
onMounted(() => {
  setInterval(fetchOrders, 5000)
})

// GOOD: WebSocket + reduced polling fallback
onMounted(() => {
  if (!marketStore.connected) {
    marketStore.connect()
  }

  watch(() => marketStore.lastMessage, (message) => {
    if (message?.type === 'order_update') {
      handleOrderUpdate(message.data)
    }
  })

  setInterval(fetchOrders, 30000) // Fallback only
})
```

### ❌ Multiple Polling Intervals

```javascript
// BAD: Multiple short intervals
setInterval(fetchMarket, 1000)
setInterval(fetchOrders, 3000)
setInterval(fetchAccount, 5000)

// GOOD: Single WebSocket connection
watch(() => marketStore.lastMessage, (message) => {
  switch (message?.type) {
    case 'market_data':
      handleMarketUpdate(message.data)
      break
    case 'order_update':
      handleOrderUpdate(message.data)
      break
    case 'account_balance':
      handleAccountUpdate(message.data)
      break
  }
})
```

## WebSocket Usage Patterns

### Pattern 1: Full WebSocket (Real-time Data)

**Use for**: Market data, order updates, position changes

```javascript
import { watch, onMounted } from 'vue'
import { useMarketStore } from '@/stores/market'

const marketStore = useMarketStore()

onMounted(() => {
  if (!marketStore.connected) {
    marketStore.connect()
  }
})

watch(() => marketStore.marketData, (newData) => {
  // Handle real-time market data updates
  updatePrices(newData)
})
```

### Pattern 2: Hybrid Mode (History + Real-time)

**Use for**: Charts, historical data with live updates

```javascript
onMounted(async () => {
  // Fetch historical data via API
  await fetchHistoricalData()

  // Connect WebSocket for real-time updates
  if (!marketStore.connected) {
    marketStore.connect()
  }

  // Reduced polling as fallback (30s+)
  updateInterval = setInterval(fetchHistoricalData, 30000)
})

watch(() => marketStore.marketData, (newData) => {
  // Append real-time updates to chart
  appendToChart(newData)
})
```

### Pattern 3: Multi-Message Pattern

**Use for**: Components watching multiple message types

```javascript
watch(() => marketStore.lastMessage, (message) => {
  if (!message) return

  switch (message.type) {
    case 'order_update':
      handleOrderUpdate(message.data)
      break
    case 'risk_alert':
      handleRiskAlert(message.data)
      break
    case 'account_balance':
      handleAccountUpdate(message.data)
      break
  }
})
```

## Code Review Checklist

When reviewing pull requests, check for:

- [ ] No new `setInterval` with API calls at intervals < 30s
- [ ] WebSocket connection established in `onMounted`
- [ ] Proper cleanup in `onUnmounted` (clear intervals, unwatch)
- [ ] Fallback polling at 30s+ intervals (if needed)
- [ ] Using `marketStore.lastMessage` for multi-message watching
- [ ] No duplicate WebSocket connections
- [ ] Proper error handling for WebSocket disconnections

## Testing Guidelines

### Manual Testing

1. **WebSocket Connection**:
   - Open browser DevTools → Network → WS
   - Verify single WebSocket connection
   - Check message flow (should see real-time updates)

2. **Fallback Behavior**:
   - Disconnect WebSocket (close connection in DevTools)
   - Verify fallback polling activates
   - Reconnect and verify WebSocket resumes

3. **Performance**:
   - Open DevTools → Network
   - Monitor HTTP requests over 1 minute
   - Should see < 20 requests/min (vs 240+ before)

### Automated Testing

```javascript
// Example test for WebSocket usage
describe('OrderMonitor', () => {
  it('should use WebSocket for real-time updates', () => {
    const wrapper = mount(OrderMonitor)

    // Verify WebSocket connection
    expect(marketStore.connect).toHaveBeenCalled()

    // Verify watching for messages
    expect(wrapper.vm.unwatchOrders).toBeDefined()

    // Verify reduced polling interval
    expect(wrapper.vm.updateInterval).toBeGreaterThanOrEqual(30000)
  })
})
```

## Monitoring

### WebSocket Health Dashboard

**Location**: System view → WebSocket Monitor tab

**Metrics to watch**:
- Connection status (should be "Connected")
- Message rate (should be > 0 msg/s)
- Uptime (should be stable)
- Message type distribution

**Alerts**:
- Connection failures > 3 in 5 minutes
- Message rate drops to 0 for > 30 seconds
- Reconnection loops (> 5 reconnects/minute)

## Rollback Plan

If WebSocket issues occur:

1. **Temporary Fallback**:
   ```javascript
   // Increase fallback polling frequency temporarily
   setInterval(fetchData, 10000) // Instead of 30000
   ```

2. **Disable WebSocket**:
   ```javascript
   // Comment out WebSocket connection
   // if (!marketStore.connected) {
   //   marketStore.connect()
   // }
   ```

3. **Full Rollback**:
   ```bash
   # Revert to pre-WebSocket commit
   git revert <websocket-commit-hash>
   ```

## Support

### Common Issues

**Issue**: WebSocket not connecting
- Check backend WebSocket endpoint is running
- Verify authentication token is valid
- Check browser console for errors

**Issue**: Duplicate updates
- Ensure only one WebSocket connection per component
- Check for multiple watch() calls on same data

**Issue**: Stale data after reconnection
- Implement full data refresh on reconnect
- Use hybrid mode with fallback polling

### Resources

- [WebSocket Transformation Progress](./WEBSOCKET_TRANSFORMATION_PROGRESS.md)
- [WebSocket Executive Summary](./WEBSOCKET_EXECUTIVE_SUMMARY.md)
- [Market Store Documentation](./frontend/src/stores/market.js)
- [WebSocket Monitor Component](./frontend/src/components/system/WebSocketMonitor.vue)

## Maintenance

### Monthly Review

- [ ] Check WebSocket connection stability metrics
- [ ] Review any new components for polling patterns
- [ ] Update this guide with new patterns/issues
- [ ] Verify pre-commit hook is still active

### Quarterly Audit

- [ ] Run full codebase scan for polling patterns
- [ ] Review WebSocket performance metrics
- [ ] Update CI/CD checks if needed
- [ ] Train new developers on WebSocket patterns

## Success Metrics

**Current Status** (as of 2026-02-24):
- ✅ 93% reduction in HTTP requests (240+ → 16/min)
- ✅ 10x faster data updates (<100ms vs 1000ms)
- ✅ 13/22 components transformed (59%)
- ✅ Pre-commit hook installed
- ⏳ CI/CD integration pending
- ⏳ Automated testing pending

**Target Metrics**:
- Maintain < 20 HTTP requests/min per user
- Keep data latency < 100ms for real-time updates
- Zero new polling patterns introduced
- 100% WebSocket uptime (with automatic reconnection)
