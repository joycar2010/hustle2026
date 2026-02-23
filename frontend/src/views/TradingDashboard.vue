<template>
  <div class="flex h-screen bg-[#1a1d21] text-white overflow-hidden">
    <!-- Left Sidebar - Account Status -->
    <aside class="w-80 bg-[#1e2329] border-r border-[#2b3139] flex flex-col">
      <AccountStatusPanel />
      <NavigationPanel />
    </aside>

    <!-- Main Content Area -->
    <main class="flex-1 flex flex-col overflow-hidden">
      <!-- Top Section - Real-time Price Monitoring -->
      <section v-show="!topHidden" class="h-[47%] border-b border-[#2b3139] flex relative">
        <!-- Spread Chart -->
        <div class="flex-1 bg-[#1e2329] border-r border-[#2b3139] relative">
          <SpreadChart />
          <!-- Toggle button on SpreadChart -->
          <button
            @click="topHidden = true"
            class="absolute top-2 right-2 z-10 flex items-center gap-1 px-2 py-1 bg-[#2b3139] hover:bg-[#363d47] text-xs text-gray-400 hover:text-white rounded transition-colors"
            title="隐藏顶部，展开策略面板"
          >
            <span>▲ 隐藏</span>
          </button>
        </div>

        <!-- Market Cards -->
        <div class="w-80 bg-[#1e2329] border-r border-[#2b3139]">
          <MarketCards />
        </div>

        <!-- Manual Trading -->
        <div class="w-96 bg-[#1e2329] relative">
          <ManualTrading />
          <!-- Toggle button on ManualTrading -->
          <button
            @click="topHidden = true"
            class="absolute top-2 right-2 z-10 flex items-center gap-1 px-2 py-1 bg-[#2b3139] hover:bg-[#363d47] text-xs text-gray-400 hover:text-white rounded transition-colors"
            title="隐藏顶部，展开策略面板"
          >
            <span>▲ 隐藏</span>
          </button>
        </div>
      </section>

      <!-- Middle Section - Strategy Configuration -->
      <section :class="['border-b border-[#2b3139] flex gap-2 p-2', topHidden ? 'flex-1' : 'h-[30%]']">
        <div class="flex-1 bg-[#1e2329] rounded relative">
          <StrategyPanel type="reverse" />
          <!-- Toggle button when top is hidden -->
          <button
            v-if="topHidden"
            @click="topHidden = false"
            class="absolute top-2 right-2 z-10 flex items-center gap-1 px-2 py-1 bg-[#2b3139] hover:bg-[#363d47] text-xs text-gray-400 hover:text-white rounded transition-colors"
            title="显示顶部面板"
          >
            <span>▼ 显示</span>
          </button>
        </div>
        <div class="flex-1 bg-[#1e2329] rounded">
          <StrategyPanel type="forward" />
        </div>
      </section>

      <!-- Bottom Section - Monitoring & Trading -->
      <section class="flex-1 flex gap-2 p-2">
        <div class="flex-1 bg-[#1e2329] rounded">
          <OrderMonitor />
        </div>
        <div class="w-96 bg-[#1e2329] rounded">
          <SpreadDataTable />
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import NavigationPanel from '@/components/trading/NavigationPanel.vue'
import SpreadChart from '@/components/trading/SpreadChart.vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import SpreadDataTable from '@/components/trading/SpreadDataTable.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'
import OrderMonitor from '@/components/trading/OrderMonitor.vue'
import ManualTrading from '@/components/trading/ManualTrading.vue'

const topHidden = ref(false)
</script>