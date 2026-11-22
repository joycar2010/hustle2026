<template>
  <div class="trading-dashboard">
    <!-- Left Sidebar - Account Status (Hidden on mobile) -->
    <aside v-if="showLeftSidebar" class="sidebar-left">
      <div class="sidebar-section account-section">
        <AccountStatusPanel />
      </div>
      <button
        @click="showLeftSidebar = false"
        class="sidebar-toggle-btn"
        title="隐藏左侧栏"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
        </svg>
      </button>
    </aside>

    <!-- Show Left Sidebar Button -->
    <button
      v-if="!showLeftSidebar"
      @click="showLeftSidebar = true"
      class="show-sidebar-btn left"
      title="显示左侧栏"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
      </svg>
    </button>

    <!-- Main Content Area -->
    <main class="main-content">
      <!-- Strategy Panels Section -->
      <section class="section-strategies">
        <div class="strategy-container reverse-strategy">
          <StrategyPanel type="reverse" :marketCardsRef="marketCardsRef" />
        </div>

        <div class="market-cards-container">
          <MarketCards ref="marketCardsRef" />
        </div>

        <div class="strategy-container forward-strategy">
          <StrategyPanel type="forward" :marketCardsRef="marketCardsRef" />
        </div>
      </section>

      <!-- Manual Trading Section (拆分后的两个组件) -->
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
    <aside v-if="showRightSidebar" class="sidebar-right">
      <Risk />
      <button
        @click="showRightSidebar = false"
        class="sidebar-toggle-btn-right"
        title="隐藏右侧栏"
      >
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
        </svg>
      </button>
    </aside>

    <!-- Show Right Sidebar Button -->
    <button
      v-if="!showRightSidebar"
      @click="showRightSidebar = true"
      class="show-sidebar-btn right"
      title="显示右侧栏"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
      </svg>
    </button>

    <!-- Floating Action Buttons (仅移动端显示) -->
    <FloatingActionButtons />
  </div>
</template>

<script setup>
import { ref, watch, onMounted, defineAsyncComponent } from 'vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'

// 懒加载非关键组件，提升初始加载速度
const AccountStatusPanel = defineAsyncComponent(() => import('@/components/trading/AccountStatusPanel.vue'))
const EmergencyManualTrading = defineAsyncComponent(() => import('@/components/trading/EmergencyManualTrading.vue'))
const RecentTradingRecords = defineAsyncComponent(() => import('@/components/trading/RecentTradingRecords.vue'))
const FloatingActionButtons = defineAsyncComponent(() => import('@/components/trading/FloatingActionButtons.vue'))
const Risk = defineAsyncComponent(() => import('@/views/Risk.vue'))

const recentRecordsRef = ref(null)
const marketCardsRef = ref(null)

// 从localStorage加载侧边栏状态
const showLeftSidebar = ref(true)
const showRightSidebar = ref(true)

onMounted(() => {
  const savedLeftState = localStorage.getItem('showLeftSidebar')
  if (savedLeftState !== null) {
    showLeftSidebar.value = savedLeftState === 'true'
  }

  const savedRightState = localStorage.getItem('showRightSidebar')
  if (savedRightState !== null) {
    showRightSidebar.value = savedRightState === 'true'
  }
})

// 监听状态变化并保存到localStorage
watch(showLeftSidebar, (newValue) => {
  localStorage.setItem('showLeftSidebar', newValue.toString())
})

watch(showRightSidebar, (newValue) => {
  localStorage.setItem('showRightSidebar', newValue.toString())
})

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
  /* 优化移动端触摸滚动 */
  -webkit-overflow-scrolling: touch;
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
  position: relative;
}

.sidebar-section {
  overflow-y: auto;
}

.account-section {
  flex: 1;
}

.sidebar-toggle-btn {
  position: absolute;
  bottom: 10px;
  right: 10px;
  padding: 8px;
  background-color: #252930;
  border: 1px solid #2b3139;
  border-radius: 4px;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 10;
}

.sidebar-toggle-btn:hover {
  background-color: #2b3139;
  border-color: #f0b90b;
  color: #f0b90b;
}

.show-sidebar-btn {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  padding: 12px 6px;
  background-color: #252930;
  border: 1px solid #2b3139;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 100;
  border-radius: 0 4px 4px 0;
}

.show-sidebar-btn.left {
  left: 0;
}

.show-sidebar-btn.right {
  right: 0;
  border-radius: 4px 0 0 4px;
}

.show-sidebar-btn:hover {
  background-color: #2b3139;
  border-color: #f0b90b;
  color: #f0b90b;
}

.show-sidebar-btn.left:hover {
  padding-right: 10px;
}

.show-sidebar-btn.right:hover {
  padding-left: 10px;
}

.sidebar-right {
  width: 320px;
  background-color: #1e2329;
  border-left: 1px solid #2b3139;
  overflow-y: auto;
  flex-shrink: 0;
  position: relative;
}

.sidebar-toggle-btn-right {
  position: absolute;
  bottom: 10px;
  left: 10px;
  padding: 8px;
  background-color: #252930;
  border: 1px solid #2b3139;
  border-radius: 4px;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 10;
}

.sidebar-toggle-btn-right:hover {
  background-color: #2b3139;
  border-color: #f0b90b;
  color: #f0b90b;
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
  flex: 1;
  display: flex;
  gap: 12px;
  padding: 12px;
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

/* ========== 手动交易区域（新增） ========== */
.section-manual-trading {
  display: none; /* PC端默认隐藏，移动端显示 */
}

/* ========== 移动端H5竖屏适配 (包括2K屏幕如小米15 Pro) ========== */
@media (orientation: portrait) and (max-width: 1500px), (max-width: 750px) {
  .trading-dashboard {
    flex-direction: column;
    height: auto;
    min-height: 100vh;
    overflow-y: auto;
    overflow-x: hidden;
    width: 100%;
  }

  /* 隐藏侧边栏 */
  .sidebar-left,
  .sidebar-right,
  .show-sidebar-btn {
    display: none;
  }

  /* 主内容区域 */
  .main-content {
    width: 100%;
    height: auto;
    padding: 8px;
    gap: 12px;
    overflow: visible;
    flex: none;
  }

  /* 策略面板区域 - 垂直排列 */
  .section-strategies {
    height: auto;
    flex-direction: column;
    padding: 0;
    border-bottom: none;
    gap: 12px;
    flex: none;
    width: 100%;
  }

  .strategy-container {
    width: 100% !important;
    max-width: 100vw !important;
    height: auto;
    min-height: 280px;
    max-height: none;
    flex: none;
  }

  .market-cards-container {
    width: 100% !important;
    max-width: 100vw !important;
    height: auto;
    min-height: 280px;
    max-height: none;
    flex: none;
  }

  /* 手动交易区域 - 移动端隐藏 */
  .section-manual-trading {
    display: none;
  }
}

/* ========== 平板适配 (768px - 1023px) ========== */
@media (min-width: 768px) and (max-width: 1023px) {
  .sidebar-left {
    width: 240px;
  }

  .sidebar-right {
    display: none; /* 平板隐藏右侧边栏 */
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
    width: 360px;
  }

  .market-cards-container {
    width: 420px;
  }
}
</style>
