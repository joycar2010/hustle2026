<template>
  <div class="flex h-screen bg-[#1a1d21] text-white overflow-hidden">
    <!-- Left Sidebar - Account Status -->
    <aside class="w-80 bg-[#1e2329] border-r border-[#2b3139] flex flex-col overflow-hidden">
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
      <section class="h-[60%] border-b border-[#2b3139] flex gap-2 p-2">
        <!-- Reverse Strategy Panel -->
        <div class="flex-1 bg-[#1e2329] rounded overflow-hidden">
          <StrategyPanel type="reverse" />
        </div>

        <!-- Market Cards (Middle) - Changed from ManualTrading -->
        <div class="w-96 bg-[#1e2329] rounded overflow-hidden flex-shrink-0">
          <MarketCards />
        </div>

        <!-- Forward Strategy Panel -->
        <div class="flex-1 bg-[#1e2329] rounded overflow-hidden">
          <StrategyPanel type="forward" />
        </div>
      </section>

      <!-- Bottom Section - Order Monitor & Market Cards -->
      <section class="flex-1 flex gap-2 p-2 min-h-0">
        <!-- Order Monitor (Left) - Increased width to 45% -->
        <div class="w-[45%] bg-[#1e2329] rounded overflow-hidden flex-shrink-0">
          <OrderMonitor />
        </div>

        <!-- Manual Trading (Right) - Changed from MarketCards, Decreased width to 55% -->
        <div class="w-[55%] bg-[#1e2329] rounded overflow-hidden flex-shrink-0">
          <ManualTrading />
        </div>
      </section>
    </main>

    <!-- Right Sidebar - Risk Management -->
    <aside class="w-80 bg-[#1e2329] border-l border-[#2b3139] flex flex-col overflow-hidden">
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