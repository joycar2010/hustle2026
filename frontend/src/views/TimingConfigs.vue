<template>
  <div class="timing-configs-container">
    <div class="header">
      <h2>时间配置管理</h2>
      <button @click="handleReload" class="reload-btn" :disabled="loading">
        <span v-if="!loading">🔄 重载配置</span>
        <span v-else>加载中...</span>
      </button>
    </div>

    <div v-if="error" class="error-message">{{ error }}</div>
    <div v-if="successMessage" class="success-message">{{ successMessage }}</div>

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="['tab-btn', { active: activeTab === tab.key }]"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="tab-content">
      <!-- Global Config -->
      <div v-if="activeTab === 'global'" class="config-panel">
        <h3>全局默认配置</h3>
        <p class="description">全局配置将作为所有策略的默认值</p>
        <ConfigForm
          v-if="globalConfig"
          :config="globalConfig"
          :config-level="'global'"
          @save="handleSave"
        />
      </div>

      <!-- Strategy Type Configs -->
      <div v-else-if="activeTab !== 'global'" class="config-panel">
        <h3>{{ getTabLabel(activeTab) }}</h3>
        <p class="description">策略类型配置将覆盖全局配置</p>
        <ConfigForm
          v-if="getStrategyTypeConfig(activeTab)"
          :config="getStrategyTypeConfig(activeTab)"
          :config-level="'strategy_type'"
          :strategy-type="activeTab"
          @save="handleSave"
        />
        <div v-else class="no-config">
          <p>该策略类型暂无配置，将使用全局配置</p>
          <button @click="createStrategyTypeConfig(activeTab)" class="create-btn">
            创建策略类型配置
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { useTimingConfigStore } from '@/stores/timingConfig'
import ConfigForm from '@/components/timing/ConfigForm.vue'

export default {
  name: 'TimingConfigs',
  components: {
    ConfigForm
  },
  setup() {
    const timingConfigStore = useTimingConfigStore()
    const activeTab = ref('global')
    const error = ref(null)
    const successMessage = ref(null)
    const loading = ref(false)

    const tabs = [
      { key: 'global', label: '全局配置' },
      { key: 'reverse_opening', label: '反向开仓' },
      { key: 'reverse_closing', label: '反向平仓' },
      { key: 'forward_opening', label: '正向开仓' },
      { key: 'forward_closing', label: '正向平仓' }
    ]

    const globalConfig = computed(() => {
      return timingConfigStore.globalConfig
    })

    const getStrategyTypeConfig = (strategyType) => {
      return timingConfigStore.getConfigByLevel('strategy_type', strategyType)
    }

    const getTabLabel = (key) => {
      return tabs.find(t => t.key === key)?.label || key
    }

    const loadConfigs = async () => {
      loading.value = true
      error.value = null
      try {
        await timingConfigStore.fetchConfigs()
      } catch (err) {
        error.value = err.response?.data?.detail || '加载配置失败'
      } finally {
        loading.value = false
      }
    }

    const handleSave = async (configData) => {
      error.value = null
      successMessage.value = null
      try {
        if (configData.id) {
          await timingConfigStore.updateConfig(configData.id, configData)
          successMessage.value = '配置更新成功'
        } else {
          await timingConfigStore.createConfig(configData)
          successMessage.value = '配置创建成功'
        }
        setTimeout(() => {
          successMessage.value = null
        }, 3000)
      } catch (err) {
        error.value = err.response?.data?.detail || '保存配置失败'
      }
    }

    const createStrategyTypeConfig = async (strategyType) => {
      error.value = null
      try {
        const defaultConfig = {
          config_level: 'strategy_type',
          strategy_type: strategyType,
          trigger_check_interval: 0.5,
          binance_timeout: 5.0,
          bybit_timeout: 0.1,
          order_check_interval: 0.2,
          spread_check_interval: 2.0,
          mt5_deal_sync_wait: 3.0,
          api_spam_prevention_delay: 3.0,
          delayed_single_leg_check_delay: 10.0,
          delayed_single_leg_second_check_delay: 1.0,
          api_retry_times: 3,
          api_retry_delay: 0.5,
          max_binance_limit_retries: 25,
          open_wait_after_cancel_no_trade: 3.0,
          open_wait_after_cancel_part: 2.0,
          close_wait_after_cancel_no_trade: 3.0,
          close_wait_after_cancel_part: 2.0
        }
        await timingConfigStore.createConfig(defaultConfig)
        successMessage.value = '策略类型配置创建成功'
        setTimeout(() => {
          successMessage.value = null
        }, 3000)
      } catch (err) {
        error.value = err.response?.data?.detail || '创建配置失败'
      }
    }

    const handleReload = async () => {
      error.value = null
      successMessage.value = null
      try {
        await timingConfigStore.reloadConfigs()
        successMessage.value = '配置重载触发成功'
        setTimeout(() => {
          successMessage.value = null
        }, 3000)
      } catch (err) {
        error.value = err.response?.data?.detail || '触发重载失败'
      }
    }

    onMounted(() => {
      loadConfigs()
    })

    return {
      activeTab,
      tabs,
      error,
      successMessage,
      loading,
      globalConfig,
      getStrategyTypeConfig,
      getTabLabel,
      handleSave,
      createStrategyTypeConfig,
      handleReload
    }
  }
}
</script>

<style scoped>
.timing-configs-container {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header h2 {
  margin: 0;
  font-size: 24px;
  color: #333;
}

.reload-btn {
  padding: 8px 16px;
  background-color: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.reload-btn:hover:not(:disabled) {
  background-color: #45a049;
}

.reload-btn:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}

.error-message {
  padding: 12px;
  background-color: #ffebee;
  color: #c62828;
  border-radius: 4px;
  margin-bottom: 16px;
}

.success-message {
  padding: 12px;
  background-color: #e8f5e9;
  color: #2e7d32;
  border-radius: 4px;
  margin-bottom: 16px;
}

.tabs {
  display: flex;
  border-bottom: 2px solid #e0e0e0;
  margin-bottom: 20px;
}

.tab-btn {
  padding: 12px 24px;
  background: none;
  border: none;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  font-size: 16px;
  color: #666;
  transition: all 0.3s;
}

.tab-btn:hover {
  color: #333;
  background-color: #f5f5f5;
}

.tab-btn.active {
  color: #1976d2;
  border-bottom-color: #1976d2;
  font-weight: 600;
}

.config-panel {
  background: white;
  padding: 24px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.config-panel h3 {
  margin-top: 0;
  margin-bottom: 8px;
  font-size: 20px;
  color: #333;
}

.description {
  color: #666;
  margin-bottom: 24px;
  font-size: 14px;
}

.no-config {
  text-align: center;
  padding: 40px;
}

.no-config p {
  color: #666;
  margin-bottom: 16px;
}

.create-btn {
  padding: 10px 20px;
  background-color: #1976d2;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.create-btn:hover {
  background-color: #1565c0;
}
</style>
