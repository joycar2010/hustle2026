<template>
  <div class="trading-dashboard">
    <!-- Left Sidebar - Account Status (Hidden on mobile) -->
    <aside class="sidebar-left">
      <div class="sidebar-section account-section">
        <AccountStatusPanel />
      </div>
      <div class="sidebar-section navigation-section">
        <NavigationPanel />
      </div>
    </aside>

    <!-- Main Content Area -->
    <main class="main-content">
      <!-- Strategy Panels Section -->
      <section class="section-strategies">
        <div class="strategy-container reverse-strategy">
          <StrategyPanel type="reverse" />
        </div>

        <div class="market-cards-container">
          <MarketCards />
        </div>

        <div class="strategy-container forward-strategy">
          <StrategyPanel type="forward" />
        </div>
      </section>

      <!-- Orders and Manual Trading Section -->
      <section class="section-orders-spread">
        <div class="order-monitor-wrapper">
          <OrderMonitor />
        </div>

        <!-- PC端显示ManualTrading，移动端隐藏 -->
        <div class="manual-trading-wrapper-pc">
          <ManualTrading />
        </div>
      </section>

      <!-- Manual Trading Section (仅移动端显示拆分后的组件) -->
      <section class="section-manual-trading">
        <div class="emergency-trading-wrapper">
          <EmergencyManualTrading @orderExecuted="handleOrderExecuted" />
        </div>

        <div class="recent-records-wrapper">
          <RecentTradingRecords ref="recentRecordsRef" />
        </div>
      </section>
    </main>

    <!-- Right Sidebar - Risk Management (Hidden on mobile/tablet) -->
    <aside class="sidebar-right">
      <Risk />
    </aside>

    <!-- Floating Action Buttons (仅移动端显示) -->
    <FloatingActionButtons />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import NavigationPanel from '@/components/trading/NavigationPanel.vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'
import OrderMonitor from '@/components/trading/OrderMonitor.vue'
import ManualTrading from '@/components/trading/ManualTrading.vue'
import EmergencyManualTrading from '@/components/trading/EmergencyManualTrading.vue'
import RecentTradingRecords from '@/components/trading/RecentTradingRecords.vue'
import FloatingActionButtons from '@/components/trading/FloatingActionButtons.vue'
import Risk from '@/views/Risk.vue'

const recentRecordsRef = ref(null)

// 当紧急交易执行后，刷新最近交易记录
function handleOrderExecuted() {
  if (recentRecordsRef.value) {
    recentRecordsRef.value.fetchRecentOrders()
  }
}
</script>

<style scoped>
.trading-dashboard {
  display: flex;
  height: 100vh;
  background-color: #1a1d21;
  color: #ffffff;
  overflow: hidden;
}

/* ========== 侧边栏样式 ========== */
.sidebar-left {
  width: 280px;
  background-color: #1e2329;
  border-right: 1px solid #2b3139;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.sidebar-section {
  overflow-y: auto;
}

.account-section {
  flex: 6.3;
}

.navigation-section {
  flex: 3.7;
}

.sidebar-right {
  width: 304px;
  background-color: #1e2329;
  border-left: 1px solid #2b3139;
  overflow-y: auto;
  flex-shrink: 0;
}

/* ========== 主内容区域 ========== */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* ========== 策略面板区域 ========== */
.section-strategies {
  height: 63%;
  display: flex;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid #2b3139;
  min-height: 0;
}

.strategy-container {
  flex: 1;
  background-color: #1e2329;
  border-radius: 8px;
  overflow: hidden;
  min-width: 0;
}

.market-cards-container {
  width: 380px;
  background-color: #1e2329;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}

/* ========== 订单和点差区域 ========== */
.section-orders-spread {
  flex: 1;
  display: flex;
  gap: 8px;
  padding: 0 8px 8px 8px;
  min-height: 0;
}

.order-monitor-wrapper {
  flex: 1;
  background-color: #1e2329;
  border-radius: 8px;
  overflow: hidden;
  min-width: 0;
}

.manual-trading-wrapper-pc {
  flex: 1;
  background-color: #1e2329;
  border-radius: 8px;
  overflow: hidden;
  min-width: 0;
}

/* ========== 手动交易区域（PC端隐藏，移动端显示） ========== */
.section-manual-trading {
  display: none;
}

/* ========== 移动端H5竖屏适配 ========== */
@media (orientation: portrait), (max-width: 750px) {
  .trading-dashboard {
    flex-direction: column;
  }

  /* 隐藏侧边栏 */
  .sidebar-left,
  .sidebar-right {
    display: none;
  }

  /* 主内容区域 */
  .main-content {
    width: 100%;
    padding: 0;
    gap: 0;
    overflow-y: auto;
  }

  /* 策略面板区域 - 垂直排列 */
  .section-strategies {
    height: auto;
    flex-direction: column;
    padding: 0;
    border-bottom: none;
    gap: 0;
  }

  .strategy-container {
    width: 100%;
    height: auto;
    min-height: auto;
    border-radius: 0;
  }

  .market-cards-container {
    width: 100%;
    height: auto;
    border-radius: 0;
  }

  /* 订单和手动交易区域 - 垂直排列 */
  .section-orders-spread {
    flex-direction: column;
    padding: 0;
    gap: 0;
  }

  .order-monitor-wrapper {
    width: 100%;
    max-height: 350px;
    border-radius: 0;
  }

  /* PC端的ManualTrading在移动端隐藏 */
  .manual-trading-wrapper-pc {
    display: none;
  }

  /* 手动交易区域 - 显示并垂直排列 */
  .section-manual-trading {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .emergency-trading-wrapper,
  .recent-records-wrapper {
    width: 100%;
    max-height: 400px;
    border-radius: 0;
  }
}

/* ========== 平板适配 (768px - 1023px) ========== */
@media (min-width: 768px) and (max-width: 1023px) {
  .sidebar-left {
    width: 240px;
  }

  .sidebar-right {
    display: none;
  }

  .market-cards-container {
    width: 320px;
  }
}

/* ========== PC端大屏优化 (≥1440px) ========== */
@media (min-width: 1440px) {
  .sidebar-left {
    width: 320px;
  }

  .sidebar-right {
    width: 342px;
  }

  .market-cards-container {
    width: 420px;
  }
}
</style>