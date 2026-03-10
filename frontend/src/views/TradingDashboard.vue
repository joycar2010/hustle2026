<template>
  <div class="flex bg-[#1a1d21] text-white lg:h-screen lg:overflow-hidden max-lg:min-h-screen max-lg:overflow-visible">
    <!-- Left Sidebar - Account Status (Hidden on mobile/tablet) -->
    <aside
      v-if="showLeftPanel"
      class="hidden lg:flex lg:w-[280px] xl:w-[320px] bg-[#1e2329] border-r border-[#2b3139] flex-col overflow-hidden flex-shrink-0"
    >
      <div class="flex-[6.3] overflow-y-auto">
        <AccountStatusPanel />
      </div>
      <div class="flex-[3.7] overflow-y-auto">
        <NavigationPanel @toggle-panel="toggleLeftPanel" />
      </div>
    </aside>

    <!-- Toggle Button for Left Panel (when panel is hidden) -->
    <button
      v-if="!showLeftPanel"
      @click="toggleLeftPanel"
      class="hidden lg:block fixed left-0 top-1/2 -translate-y-1/2 bg-[#1e2329] border border-l-0 border-[#2b3139] rounded-r-lg p-3 px-1.5 text-white cursor-pointer transition-all duration-300 z-[100] shadow-[2px_0_8px_rgba(0,0,0,0.3)] hover:bg-[#2b3139] hover:pr-2"
      title="显示左侧面板"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
      </svg>
    </button>

    <!-- Main Content Area -->
    <main class="flex-1 flex flex-col min-w-0 overflow-hidden lg:overflow-hidden max-lg:overflow-visible max-lg:h-auto">
      <!-- Strategy Panels Section -->
      <section class="flex-1 flex flex-col lg:flex-row gap-2 p-2 min-h-0 max-lg:h-auto">
        <!-- Reverse Strategy -->
        <div class="flex-1 bg-[#1e2329] rounded-lg min-w-0 lg:min-h-0 lg:overflow-hidden max-lg:overflow-visible">
          <StrategyPanel type="reverse" :market-cards-ref="marketCardsRef" />
        </div>

        <!-- Market Cards -->
        <div class="w-full lg:w-[380px] xl:w-[420px] bg-[#1e2329] rounded-lg flex-shrink-0 lg:min-h-0 lg:overflow-hidden max-lg:overflow-visible">
          <MarketCards ref="marketCardsRef" />
        </div>

        <!-- Forward Strategy -->
        <div class="flex-1 bg-[#1e2329] rounded-lg min-w-0 lg:min-h-0 lg:overflow-hidden max-lg:overflow-visible">
          <StrategyPanel type="forward" :market-cards-ref="marketCardsRef" />
        </div>
      </section>
    </main>

    <!-- Right Sidebar - Risk Management (Hidden on mobile/tablet) -->
    <aside
      v-if="showRiskPanel"
      class="hidden xl:block w-[304px] 2xl:w-[342px] bg-[#1e2329] border-l border-[#2b3139] overflow-y-auto flex-shrink-0"
    >
      <Risk @toggle-panel="toggleRiskPanel" />
    </aside>

    <!-- Toggle Button (when panel is hidden) -->
    <button
      v-if="!showRiskPanel"
      @click="toggleRiskPanel"
      class="hidden xl:block fixed right-0 top-1/2 -translate-y-1/2 bg-[#1e2329] border border-r-0 border-[#2b3139] rounded-l-lg p-3 px-1.5 text-white cursor-pointer transition-all duration-300 z-[100] shadow-[-2px_0_8px_rgba(0,0,0,0.3)] hover:bg-[#2b3139] hover:pl-2"
      title="显示风险控制面板"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
      </svg>
    </button>

    <!-- Floating Action Buttons (Mobile only) -->
    <FloatingActionButtons />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import NavigationPanel from '@/components/trading/NavigationPanel.vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'
import FloatingActionButtons from '@/components/trading/FloatingActionButtons.vue'
import Risk from '@/views/Risk.vue'

// 从 localStorage 加载面板状态
function loadPanelState(key, defaultValue = true) {
  try {
    const saved = localStorage.getItem(key)
    return saved !== null ? saved === 'true' : defaultValue
  } catch {
    return defaultValue
  }
}

// 保存面板状态到 localStorage
function savePanelState(key, value) {
  try {
    localStorage.setItem(key, value.toString())
  } catch (error) {
    console.error('Failed to save panel state:', error)
  }
}

const showRiskPanel = ref(loadPanelState('showRiskPanel', true))
const showLeftPanel = ref(loadPanelState('showLeftPanel', true))
const marketCardsRef = ref(null)

// 切换风险控制面板显示/隐藏
function toggleRiskPanel() {
  showRiskPanel.value = !showRiskPanel.value
  savePanelState('showRiskPanel', showRiskPanel.value)
}

// 切换左侧面板显示/隐藏
function toggleLeftPanel() {
  showLeftPanel.value = !showLeftPanel.value
  savePanelState('showLeftPanel', showLeftPanel.value)
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

/* ========== 风险控制面板切换按钮 ========== */
.risk-panel-toggle {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  background-color: #1e2329;
  border: 1px solid #2b3139;
  border-right: none;
  border-radius: 8px 0 0 8px;
  padding: 12px 6px;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 100;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.3);
}

.risk-panel-toggle:hover {
  background-color: #2b3139;
  padding-left: 8px;
}

.risk-panel-toggle svg {
  display: block;
}

/* ========== 左侧面板切换按钮 ========== */
.left-panel-toggle {
  position: fixed;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  background-color: #1e2329;
  border: 1px solid #2b3139;
  border-left: none;
  border-radius: 0 8px 8px 0;
  padding: 12px 6px;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.3s ease;
  z-index: 100;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.3);
}

.left-panel-toggle:hover {
  background-color: #2b3139;
  padding-right: 8px;
}

.left-panel-toggle svg {
  display: block;
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

  /* 隐藏面板切换按钮 */
  .risk-panel-toggle,
  .left-panel-toggle {
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