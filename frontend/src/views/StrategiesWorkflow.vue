<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">策略工作流配置</h1>

    <!-- 策略选择器 -->
    <div class="mb-6">
      <h2 class="text-xl font-bold mb-4">选择策略类型</h2>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <button
          v-for="strategy in strategyTypes"
          :key="strategy.type"
          @click="selectStrategy(strategy.type)"
          :class="[
            'strategy-card',
            selectedStrategy === strategy.type ? 'active' : ''
          ]"
        >
          <div class="strategy-icon">{{ strategy.icon }}</div>
          <div class="strategy-name">{{ strategy.name }}</div>
          <div class="strategy-desc">{{ strategy.description }}</div>
          <div v-if="strategyConfigs[strategy.type]" class="strategy-config">
            <span class="config-label">当前配置:</span>
            <span class="config-value">{{ getConfigName(strategyConfigs[strategy.type]) }}</span>
          </div>
        </button>
      </div>
    </div>

    <!-- 工作流画布 -->
    <div v-if="selectedStrategy" class="workflow-container">
      <StrategyWorkflow :strategy-type="selectedStrategy" :key="selectedStrategy" />
    </div>

    <!-- 提示信息 -->
    <div v-else class="empty-state card">
      <svg class="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
      <p class="text-gray-400">请选择一个策略类型查看其执行流程和配置</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import StrategyWorkflow from '@/components/workflow/StrategyWorkflow.vue'
import { useTimingConfigStore } from '@/stores/timingConfig'

const timingConfigStore = useTimingConfigStore()
const selectedStrategy = ref(null)
const strategyConfigs = ref({})

const strategyTypes = [
  {
    type: 'reverse_opening',
    name: '反向开仓',
    icon: '🔴',
    description: 'Binance做空 + Bybit做多'
  },
  {
    type: 'reverse_closing',
    name: '反向平仓',
    icon: '🟢',
    description: '平掉反向开仓的持仓'
  },
  {
    type: 'forward_opening',
    name: '正向开仓',
    icon: '🔵',
    description: 'Binance做多 + Bybit做空'
  },
  {
    type: 'forward_closing',
    name: '正向平仓',
    icon: '🟡',
    description: '平掉正向开仓的持仓'
  }
]

const templateNames = {
  'conservative': '保守型',
  'balanced': '平衡型',
  'aggressive': '激进型'
}

async function loadStrategyConfigs() {
  try {
    const configs = await timingConfigStore.fetchConfigs()
    strategyTypes.forEach(strategy => {
      const config = configs.find(c =>
        c.config_level === 'strategy_type' && c.strategy_type === strategy.type
      )
      if (config) {
        strategyConfigs.value[strategy.type] = config
      }
    })
  } catch (error) {
    console.error('Failed to load strategy configs:', error)
  }
}

function getConfigName(config) {
  if (config.template && templateNames[config.template]) {
    return templateNames[config.template]
  }
  return '自定义配置'
}

function selectStrategy(type) {
  selectedStrategy.value = type
}

onMounted(() => {
  loadStrategyConfigs()
})
</script>

<style scoped>
.card {
  background: var(--color-dark-100);
  border: 1px solid var(--color-border-primary);
  border-radius: 0.5rem;
  padding: 1.5rem;
}

.strategy-card {
  background: var(--color-dark-100);
  border: 1px solid var(--color-border-primary);
  border-radius: 0.5rem;
  padding: 1.25rem;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.strategy-card:hover {
  border-color: var(--color-primary);
  background: var(--color-dark-50);
}

.strategy-card.active {
  border-color: var(--color-primary);
  background: var(--color-dark-50);
}

.strategy-icon {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.strategy-name {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.strategy-desc {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  line-height: 1.4;
}

.strategy-config {
  margin-top: 0.5rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--color-border-secondary);
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.config-label {
  font-size: 0.6875rem;
  color: var(--color-text-tertiary);
  font-weight: 500;
}

.config-value {
  font-size: 0.75rem;
  color: var(--color-primary);
  font-weight: 600;
}

.workflow-container {
  height: 800px;
  padding: 0;
  overflow: hidden;
  background: var(--color-dark-100);
  border: 1px solid var(--color-border-primary);
  border-radius: 0.5rem;
}

.empty-state {
  text-align: center;
  padding: 3.75rem 1.25rem;
}

.empty-state svg {
  color: var(--color-text-tertiary);
}
</style>
