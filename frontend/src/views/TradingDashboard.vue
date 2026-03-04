<template>
  <div class="h-screen flex flex-col overflow-hidden bg-[#1a1d21] text-white">
    <!-- Mobile Menu Button (visible only on mobile) -->
    <div class="md:hidden fixed top-2 right-2 z-50">
      <button
        @click="showMobileMenu = !showMobileMenu"
        class="bg-[#f0b90b] text-[#1a1d21] p-2 rounded-lg shadow-lg"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
    </div>

    <!-- Mobile Menu Overlay -->
    <div
      v-if="showMobileMenu"
      class="md:hidden fixed inset-0 bg-black bg-opacity-50 z-40"
      @click="showMobileMenu = false"
    >
      <div class="absolute top-12 right-2 bg-[#252930] rounded-lg shadow-xl p-4 space-y-2" @click.stop>
        <button
          @click="showAccountPanel = true; showMobileMenu = false"
          class="w-full px-4 py-2 bg-[#1e2329] hover:bg-[#2b3139] rounded text-left text-sm"
        >
          账户状态
        </button>
        <button
          @click="showRiskPanel = true; showMobileMenu = false"
          class="w-full px-4 py-2 bg-[#1e2329] hover:bg-[#2b3139] rounded text-left text-sm"
        >
          风险控制
        </button>
      </div>
    </div>

    <!-- Account Status Modal (mobile only) -->
    <div
      v-if="showAccountPanel"
      class="md:hidden fixed inset-0 bg-black bg-opacity-75 z-50 flex items-center justify-center p-4"
      @click="showAccountPanel = false"
    >
      <div class="bg-[#1a1d21] rounded-lg w-full max-w-md h-[80vh] overflow-hidden" @click.stop>
        <div class="flex items-center justify-between p-3 border-b border-[#2b3139]">
          <h3 class="text-lg font-bold">账户状态</h3>
          <button @click="showAccountPanel = false" class="text-gray-400 hover:text-white">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="h-[calc(100%-60px)]">
          <AccountStatusPanel />
        </div>
      </div>
    </div>

    <!-- Risk Modal (mobile only) -->
    <div
      v-if="showRiskPanel"
      class="md:hidden fixed inset-0 bg-black bg-opacity-75 z-50 flex items-center justify-center p-4"
      @click="showRiskPanel = false"
    >
      <div class="bg-[#1a1d21] rounded-lg w-full max-w-md h-[80vh] overflow-hidden" @click.stop>
        <div class="flex items-center justify-between p-3 border-b border-[#2b3139]">
          <h3 class="text-lg font-bold">风险控制</h3>
          <button @click="showRiskPanel = false" class="text-gray-400 hover:text-white">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="h-[calc(100%-60px)]">
          <Risk />
        </div>
      </div>
    </div>

    <!-- Top Section: Strategy Panels + MarketCards -->
    <!-- Mobile: vertical stack, Desktop: 3 columns -->
    <section class="flex-1 flex flex-col lg:flex-row gap-2 p-2 min-h-0 overflow-y-auto lg:overflow-y-hidden">
      <!-- Reverse Strategy (mobile: full width, desktop: flex-1) -->
      <div class="w-full lg:flex-1 h-[400px] lg:h-full flex-shrink-0 bg-[#1e2329] rounded overflow-hidden">
        <StrategyPanel type="reverse" />
      </div>

      <!-- MarketCards (mobile: full width, desktop: fixed width) -->
      <div class="w-full lg:w-[380px] h-[500px] lg:h-full flex-shrink-0 bg-[#1e2329] rounded overflow-hidden">
        <MarketCards />
      </div>

      <!-- Forward Strategy (mobile: full width, desktop: flex-1) -->
      <div class="w-full lg:flex-1 h-[400px] lg:h-full flex-shrink-0 bg-[#1e2329] rounded overflow-hidden">
        <StrategyPanel type="forward" />
      </div>
    </section>

    <!-- Bottom Section: OrderMonitor + ManualTrading -->
    <!-- Mobile: vertical stack, Desktop: 2 columns -->
    <section class="flex-1 flex flex-col lg:flex-row gap-2 p-2 min-h-0 overflow-y-auto lg:overflow-y-hidden">
      <!-- OrderMonitor (mobile: full width, desktop: 53%) -->
      <div class="w-full lg:w-[53%] h-[400px] lg:h-full flex-shrink-0 bg-[#1e2329] rounded overflow-hidden">
        <OrderMonitor />
      </div>

      <!-- ManualTrading (mobile: full width, desktop: 47%) -->
      <div class="w-full lg:flex-1 h-[500px] lg:h-full flex-shrink-0 bg-[#1e2329] rounded overflow-hidden">
        <ManualTrading />
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import Risk from '@/views/Risk.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import OrderMonitor from '@/components/trading/OrderMonitor.vue'
import ManualTrading from '@/components/trading/ManualTrading.vue'

const showMobileMenu = ref(false)
const showAccountPanel = ref(false)
const showRiskPanel = ref(false)
</script>