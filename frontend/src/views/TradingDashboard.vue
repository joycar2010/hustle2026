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
      <section class="h-[45%] border-b border-[#2b3139] flex">
        <!-- Spread Chart -->
        <div class="flex-1 bg-[#1e2329] border-r border-[#2b3139]">
          <SpreadChart />
        </div>

        <!-- Market Cards -->
        <div class="w-80 bg-[#1e2329] border-r border-[#2b3139]">
          <MarketCards />
        </div>

        <!-- Spread Data Table -->
        <div class="w-96 bg-[#1e2329]">
          <SpreadDataTable />
        </div>
      </section>

      <!-- Middle Section - Strategy Configuration -->
      <section class="h-[30%] border-b border-[#2b3139] flex gap-2 p-2">
        <div class="flex-1 bg-[#1e2329] rounded">
          <StrategyPanel type="reverse" />
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
        <div class="w-80 bg-[#1e2329] rounded">
          <RiskDashboard />
        </div>
        <div class="w-80 bg-[#1e2329] rounded">
          <ManualTrading />
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import NavigationPanel from '@/components/trading/NavigationPanel.vue'
import SpreadChart from '@/components/trading/SpreadChart.vue'
import MarketCards from '@/components/trading/MarketCards.vue'
import SpreadDataTable from '@/components/trading/SpreadDataTable.vue'
import StrategyPanel from '@/components/trading/StrategyPanel.vue'
import OrderMonitor from '@/components/trading/OrderMonitor.vue'
import RiskDashboard from '@/components/trading/RiskDashboard.vue'
import ManualTrading from '@/components/trading/ManualTrading.vue'
</script>