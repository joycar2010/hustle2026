<template>
  <div class="flex flex-col h-screen bg-[#1a1d21] text-white overflow-hidden">
    <!-- Mobile Header with Navigation -->
    <div class="md:hidden flex items-center justify-between p-3 border-b border-[#2b3139] bg-[#1e2329]">
      <h1 class="text-lg font-bold">交易控制台</h1>
      <button @click="showMobileMenu = !showMobileMenu" class="p-2">
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>
        </svg>
      </button>
    </div>

    <!-- Mobile Menu Overlay -->
    <div v-if="showMobileMenu" class="md:hidden fixed inset-0 bg-black/50 z-50" @click="showMobileMenu = false">
      <div class="bg-[#1e2329] w-64 h-full p-4" @click.stop>
        <NavigationPanel @navigate="showMobileMenu = false" />
      </div>
    </div>

    <div class="flex-1 flex flex-col md:flex-row overflow-hidden">
      <!-- Left Sidebar - Account Status (Hidden on mobile) -->
      <aside class="hidden md:flex md:w-64 lg:w-80 bg-[#1e2329] border-r border-[#2b3139] flex-col overflow-hidden">
        <div class="flex-[7] overflow-y-auto">
          <AccountStatusPanel />
        </div>
        <div class="flex-[3] overflow-y-auto">
          <NavigationPanel />
        </div>
      </aside>

      <!-- Main Content - Scrollable on Mobile -->
      <main class="flex-1 overflow-y-auto md:overflow-hidden">
        <div class="md:h-full md:flex md:flex-col">
          <!-- Top Section - Strategy Panels -->
          <section class="md:h-[60%] md:border-b border-[#2b3139] flex flex-col md:flex-row gap-2 p-2">
            <!-- Reverse Strategy Panel -->
            <div class="flex-1 bg-[#1e2329] rounded overflow-hidden min-h-[400px] md:min-h-0">
              <div class="h-full flex flex-col">
                <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
                  <h2 class="text-sm font-bold">反向套利策略</h2>
                </div>
                <div class="flex-1 overflow-y-auto">
                  <StrategyPanel type="reverse" />
                </div>
              </div>
            </div>

            <!-- Market Cards (Middle) -->
            <div class="w-full md:w-80 lg:w-96 bg-[#1e2329] rounded overflow-hidden flex-shrink-0 min-h-[300px] md:min-h-0">
              <div class="h-full flex flex-col">
                <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
                  <h2 class="text-sm font-bold">点差数据流</h2>
                </div>
                <div class="flex-1 overflow-y-auto">
                  <MarketCards />
                </div>
              </div>
            </div>

            <!-- Forward Strategy Panel -->
            <div class="flex-1 bg-[#1e2329] rounded overflow-hidden min-h-[400px] md:min-h-0">
              <div class="h-full flex flex-col">
                <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
                  <h2 class="text-sm font-bold">正向套利策略</h2>
                </div>
                <div class="flex-1 overflow-y-auto">
                  <StrategyPanel type="forward" />
                </div>
              </div>
            </div>
          </section>

          <!-- Bottom Section - Order Monitor & Manual Trading -->
          <section class="md:flex-1 flex flex-col gap-2 p-2 md:min-h-0">
            <!-- Order Monitor (Left) - 策略挂单 -->
            <div class="w-full bg-[#1e2329] rounded overflow-hidden flex-shrink-0 min-h-[300px] md:min-h-0">
              <div class="h-full flex flex-col">
                <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
                  <h2 class="text-sm font-bold">策略挂单</h2>
                </div>
                <div class="flex-1 overflow-y-auto">
                  <OrderMonitor />
                </div>
              </div>
            </div>

            <!-- Manual Trading Section - Split into two panels -->
            <div class="w-full flex flex-col gap-2 flex-shrink-0">
              <!-- Emergency Trading Panel -->
              <div class="flex-1 bg-[#1e2329] rounded overflow-hidden min-h-[300px] md:min-h-0">
                <div class="h-full flex flex-col">
                  <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
                    <div class="flex items-center justify-between">
                      <h2 class="text-sm font-bold">紧急手动交易</h2>
                      <div class="flex items-center space-x-1">
                        <div class="w-2 h-2 rounded-full bg-[#f6465d] animate-pulse"></div>
                        <span class="text-xs text-[#f6465d] font-bold">紧急模式</span>
                      </div>
                    </div>
                  </div>
                  <div class="flex-1 overflow-y-auto">
                    <EmergencyTrading />
                  </div>
                </div>
              </div>

              <!-- Recent Trades Panel -->
              <div class="flex-1 bg-[#1e2329] rounded overflow-hidden min-h-[200px] md:min-h-0">
                <div class="h-full flex flex-col">
                  <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
                    <h2 class="text-sm font-bold">最近交易记录</h2>
                  </div>
                  <div class="flex-1 overflow-y-auto">
                    <RecentTrades />
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>

      <!-- Right Sidebar - Risk Management (Hidden on mobile/tablet) -->
      <aside class="hidden lg:flex lg:w-80 bg-[#1e2329] border-l border-[#2b3139] flex-col overflow-hidden">
        <div class="px-3 py-2 border-b border-[#2b3139] flex-shrink-0">
          <h2 class="text-sm font-bold">风险控制</h2>
        </div>
        <div class="flex-1 overflow-y-auto">
          <Risk />
        </div>
      </aside>
    </div>

    <!-- Mobile Risk Panel (Show as modal on mobile) -->
    <button
      v-if="!showMobileRisk"
      @click="showMobileRisk = true"
      class="lg:hidden fixed bottom-4 right-4 bg-[#f0b90b] text-black px-4 py-2 rounded-full shadow-lg z-40 font-bold text-sm"
    >
      风险控制
    </button>

    <div v-if="showMobileRisk" class="lg:hidden fixed inset-0 bg-black/50 z-50 flex items-end md:items-center md:justify-center" @click="showMobileRisk = false">
      <div class="bg-[#1e2329] w-full md:w-96 md:rounded-t-lg max-h-[80vh] overflow-hidden flex flex-col" @click.stop>
        <div class="px-3 py-3 border-b border-[#2b3139] flex items-center justify-between flex-shrink-0">
          <h2 class="text-sm font-bold">风险控制</h2>
          <button @click="showMobileRisk = false" class="text-gray-400 hover:text-white">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
        <div class="flex-1 overflow-y-auto">
          <Risk />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import NavigationPanel from '@/components/trading/NavigationPanel.vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'
import OrderMonitor from '@/components/trading/OrderMonitor.vue'
import EmergencyTrading from '@/components/trading/EmergencyTrading.vue'
import RecentTrades from '@/components/trading/RecentTrades.vue'
import Risk from '@/views/Risk.vue'

const showMobileMenu = ref(false)
const showMobileRisk = ref(false)
</script>
