<template>
  <div class="config-form">
    <form @submit.prevent="handleSubmit">
      <!-- Trigger Control Group -->
      <div class="config-group">
        <h4 class="group-title">触发控制</h4>
        <div class="form-row">
          <div class="form-field">
            <label>触发检查间隔</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.trigger_check_interval"
                step="0.1"
                min="0.1"
                max="10"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.1-10秒</span>
          </div>
        </div>
      </div>

      <!-- Order Execution Group -->
      <div class="config-group">
        <h4 class="group-title">订单执行</h4>
        <div class="form-row">
          <div class="form-field">
            <label>Binance订单监控超时</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.binance_timeout"
                step="0.1"
                min="0.1"
                max="60"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.1-60秒</span>
          </div>
          <div class="form-field">
            <label>Bybit订单执行超时</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.bybit_timeout"
                step="0.01"
                min="0.01"
                max="10"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.01-10秒</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>订单检查间隔</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.order_check_interval"
                step="0.05"
                min="0.05"
                max="5"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.05-5秒</span>
          </div>
          <div class="form-field">
            <label>点差检查间隔</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.spread_check_interval"
                step="0.1"
                min="0.1"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.1-30秒</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>MT5成交数据同步等待</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.mt5_deal_sync_wait"
                step="0.1"
                min="0.1"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.1-30秒</span>
          </div>
        </div>
      </div>

      <!-- Flow Control Group -->
      <div class="config-group">
        <h4 class="group-title">流程控制</h4>
        <div class="form-row">
          <div class="form-field">
            <label>API防止频繁调用延迟</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.api_spam_prevention_delay"
                step="0.5"
                min="0.5"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.5-30秒</span>
          </div>
          <div class="form-field">
            <label>单腿延迟检查延迟</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.delayed_single_leg_check_delay"
                step="1"
                min="1"
                max="60"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 1-60秒</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>单腿第二次检查延迟</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.delayed_single_leg_second_check_delay"
                step="0.1"
                min="0.1"
                max="10"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.1-10秒</span>
          </div>
        </div>
      </div>

      <!-- Retry Configuration Group -->
      <div class="config-group">
        <h4 class="group-title">重试配置</h4>
        <div class="form-row">
          <div class="form-field">
            <label>API重试次数</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.api_retry_times"
                step="1"
                min="1"
                max="10"
                required
              />
              <span class="unit">次</span>
            </div>
            <span class="hint">范围: 1-10次</span>
          </div>
          <div class="form-field">
            <label>API重试延迟</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.api_retry_delay"
                step="0.1"
                min="0.1"
                max="10"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.1-10秒</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>Binance限价单最大重试次数</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.max_binance_limit_retries"
                step="1"
                min="5"
                max="100"
                required
              />
              <span class="unit">次</span>
            </div>
            <span class="hint">范围: 5-100次</span>
          </div>
        </div>
      </div>

      <!-- Wait Delay Group -->
      <div class="config-group">
        <h4 class="group-title">等待延迟</h4>
        <div class="form-row">
          <div class="form-field">
            <label>开仓取消未成交后等待</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.open_wait_after_cancel_no_trade"
                step="0.5"
                min="0.5"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.5-30秒</span>
          </div>
          <div class="form-field">
            <label>开仓取消部分成交后等待</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.open_wait_after_cancel_part"
                step="0.5"
                min="0.5"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.5-30秒</span>
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>平仓取消未成交后等待</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.close_wait_after_cancel_no_trade"
                step="0.5"
                min="0.5"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.5-30秒</span>
          </div>
          <div class="form-field">
            <label>平仓取消部分成交后等待</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.close_wait_after_cancel_part"
                step="0.5"
                min="0.5"
                max="30"
                required
              />
              <span class="unit">秒</span>
            </div>
            <span class="hint">范围: 0.5-30秒</span>
          </div>
        </div>
      </div>

      <div class="form-actions">
        <button type="button" @click="resetToDefaults" class="reset-btn">
          重置为默认值
        </button>
        <button type="submit" class="save-btn" :disabled="saving">
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script>
import { ref, watch } from 'vue'

export default {
  name: 'ConfigForm',
  props: {
    config: {
      type: Object,
      required: true
    },
    configLevel: {
      type: String,
      required: true
    },
    strategyType: {
      type: String,
      default: null
    }
  },
  emits: ['save'],
  setup(props, { emit }) {
    const saving = ref(false)
    const formData = ref({})

    const initFormData = () => {
      formData.value = {
        id: props.config.id,
        config_level: props.configLevel,
        strategy_type: props.strategyType,
        trigger_check_interval: props.config.trigger_check_interval || 0.5,
        binance_timeout: props.config.binance_timeout || 5.0,
        bybit_timeout: props.config.bybit_timeout || 0.1,
        order_check_interval: props.config.order_check_interval || 0.2,
        spread_check_interval: props.config.spread_check_interval || 2.0,
        mt5_deal_sync_wait: props.config.mt5_deal_sync_wait || 3.0,
        api_spam_prevention_delay: props.config.api_spam_prevention_delay || 3.0,
        delayed_single_leg_check_delay: props.config.delayed_single_leg_check_delay || 10.0,
        delayed_single_leg_second_check_delay: props.config.delayed_single_leg_second_check_delay || 1.0,
        api_retry_times: props.config.api_retry_times || 3,
        api_retry_delay: props.config.api_retry_delay || 0.5,
        max_binance_limit_retries: props.config.max_binance_limit_retries || 25,
        open_wait_after_cancel_no_trade: props.config.open_wait_after_cancel_no_trade || 3.0,
        open_wait_after_cancel_part: props.config.open_wait_after_cancel_part || 2.0,
        close_wait_after_cancel_no_trade: props.config.close_wait_after_cancel_no_trade || 3.0,
        close_wait_after_cancel_part: props.config.close_wait_after_cancel_part || 2.0
      }
    }

    watch(() => props.config, () => {
      initFormData()
    }, { immediate: true })

    const handleSubmit = async () => {
      saving.value = true
      try {
        emit('save', formData.value)
      } finally {
        saving.value = false
      }
    }

    const resetToDefaults = () => {
      formData.value = {
        ...formData.value,
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
    }

    return {
      formData,
      saving,
      handleSubmit,
      resetToDefaults
    }
  }
}
</script>

<style scoped>
.config-form {
  max-width: 100%;
}

.config-group {
  margin-bottom: 32px;
  padding: 20px;
  background-color: #f9f9f9;
  border-radius: 8px;
}

.group-title {
  margin: 0 0 16px 0;
  font-size: 18px;
  color: #333;
  font-weight: 600;
  border-bottom: 2px solid #1976d2;
  padding-bottom: 8px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 16px;
}

.form-row:last-child {
  margin-bottom: 0;
}

.form-field {
  display: flex;
  flex-direction: column;
}

.form-field label {
  font-size: 14px;
  font-weight: 500;
  color: #555;
  margin-bottom: 8px;
}

.input-with-unit {
  display: flex;
  align-items: center;
  gap: 8px;
}

.input-with-unit input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.input-with-unit input:focus {
  outline: none;
  border-color: #1976d2;
}

.unit {
  font-size: 14px;
  color: #666;
  min-width: 30px;
}

.hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid #e0e0e0;
}

.reset-btn {
  padding: 10px 20px;
  background-color: #f5f5f5;
  color: #666;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.reset-btn:hover {
  background-color: #e0e0e0;
}

.save-btn {
  padding: 10px 24px;
  background-color: #1976d2;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.save-btn:hover:not(:disabled) {
  background-color: #1565c0;
}

.save-btn:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}
</style>
