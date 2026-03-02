<template>
  <div class="flex flex-col lg:flex-row h-screen bg-[#1a1d21] text-white overflow-hidden">
    <!-- Left Sidebar - Account Status (Hidden on mobile, shown on tablet+) -->
    <aside class="hidden md:flex md:w-64 lg:w-80 bg-[#1e2329] border-r border-[#2b3139] flex-col overflow-hidden">
      <div class="flex-[7] overflow-y-auto">
        <AccountStatusPanel />
      </div>
      <div class="flex-[3] overflow-y-auto">
        <NavigationPanel />
      </div>
    </aside>

    <!-- Main Content Area -->
    <main class="flex-1 flex flex-col overflow-hidden">
      <!-- Top Section - Strategy Configuration -->
      <section class="h-auto md:h-[60%] border-b border-[#2b3139] flex flex-col md:flex-row gap-2 p-2">
        <!-- Reverse Strategy Panel - Order 1 on mobile, 1 on desktop -->
        <div class="flex-1 bg-[#1e2329] rounded overflow-hidden min-h-[300px] md:min-h-0 order-1">
          <StrategyPanel type="reverse" />
        </div>

        <!-- Market Cards (Middle) - Order 2 on mobile, 2 on desktop -->
        <div class="w-full md:w-80 lg:w-96 bg-[#1e2329] rounded overflow-hidden flex-shrink-0 order-2">
          <MarketCards />
        </div>

        <!-- Forward Strategy Panel - Order 3 on mobile, 3 on desktop -->
        <div class="flex-1 bg-[#1e2329] rounded overflow-hidden min-h-[300px] md:min-h-0 order-3">
          <StrategyPanel type="forward" />
        </div>
      </section>

      <!-- Bottom Section - Order Monitor & Manual Trading -->
      <section class="flex-1 flex flex-col md:flex-row gap-2 p-2 min-h-0">
        <!-- Order Monitor (Left) -->
        <div class="w-full md:w-[45%] bg-[#1e2329] rounded overflow-hidden flex-shrink-0 min-h-[300px] md:min-h-0">
          <OrderMonitor />
        </div>

        <!-- Manual Trading (Right) -->
        <div class="w-full md:w-[55%] bg-[#1e2329] rounded overflow-hidden flex-shrink-0 min-h-[300px] md:min-h-0">
          <ManualTrading />
        </div>
      </section>
    </main>

    <!-- Right Sidebar - Risk Management (Hidden on mobile/tablet, shown on large screens) -->
    <aside class="hidden lg:flex lg:w-80 bg-[#1e2329] border-l border-[#2b3139] flex-col overflow-hidden">
      <Risk />
    </aside>
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
import Risk from '@/views/Risk.vue'
</script>