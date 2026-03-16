<template>
  <div class="workflow-canvas">
    <div class="canvas-header">
      <div class="header-left">
        <h2>{{ strategyName }} - 执行流程配置</h2>
        <span v-if="isLocked" class="lock-badge">
          🔒 已锁定
        </span>
      </div>
      <div class="header-actions">
        <div class="template-group">
          <button
            v-for="(template, key) in templates"
            :key="key"
            @click="applyTemplateByKey(key)"
            :class="['btn-template', { 'active': currentTemplate === key }]"
            :disabled="isLocked"
          >
            {{ template.name }}
          </button>
        </div>
        <div class="action-buttons">
          <button @click="showDocModal = true" class="btn-secondary" title="配置文档">
            📖 文档
          </button>
          <button @click="showTemplateModal = true" class="btn-secondary" title="模板管理">
            📋 模板
          </button>
          <button @click="showHistoryModal = true" class="btn-secondary" title="配置历史">
            📜 历史
          </button>
          <button @click="exportConfig" class="btn-secondary" title="导出配置">
            📤 导出
          </button>
          <button @click="importConfig" class="btn-secondary" title="导入配置" :disabled="isLocked">
            📥 导入
          </button>
          <button @click="showCompareModal = true" class="btn-secondary" title="配置对比">
            🔍 对比
          </button>
          <button @click="showSaveTemplateModal = true" class="btn-secondary" title="另存为模板">
            💾 另存为
          </button>
          <button @click="toggleLock" class="btn-secondary" :title="isLocked ? '解锁配置' : '锁定配置'">
            {{ isLocked ? '🔓 解锁' : '🔒 锁定' }}
          </button>
          <button @click="saveConfig" class="btn-primary" :disabled="saving || isLocked">
            {{ saving ? '保存中...' : '💾 保存配置' }}
          </button>
          <button @click="resetConfig" class="btn-secondary" :disabled="isLocked">
            🔄 重置
          </button>
        </div>
      </div>
    </div>

    <VueFlow
      v-model="elements"
      :default-zoom="0.75"
      :min-zoom="0.5"
      :max-zoom="1.5"
      class="workflow-flow"
    >
      <Background />
      <Controls />

      <template #node-custom="{ data }">
        <div :class="['custom-node', data.type]">
          <div class="node-header">
            <span class="node-icon">{{ data.icon }}</span>
            <span class="node-title">{{ data.label }}</span>
          </div>
          <div class="node-content">
            <div v-for="param in data.params" :key="param.key" class="param-row">
              <label :for="`${data.id}-${param.key}`">{{ param.label }}</label>
              <div class="param-input">
                <input
                  :id="`${data.id}-${param.key}`"
                  v-model.number="param.value"
                  :type="param.unit === '次' ? 'number' : 'number'"
                  :step="param.step"
                  :min="param.min"
                  :max="param.max"
                  @input="validateParam(param)"
                  @change="onParamChange(data.id, param.key, param.value)"
                  :class="{ 'warning': param.warning, 'error': param.error }"
                />
                <span class="param-unit">{{ param.unit }}</span>
              </div>
              <span class="param-hint" :class="{ 'text-warning': param.warning, 'text-error': param.error }">
                {{ param.warning || param.error || `推荐: ${param.recommended}${param.unit}` }}
              </span>
            </div>
          </div>
          <div v-if="data.description" class="node-description">
            {{ data.description }}
          </div>
          <div v-if="data.impact" class="node-impact">
            💡 {{ data.impact }}
          </div>
        </div>
      </template>
    </VueFlow>

    <div v-if="error" class="error-message">{{ error }}</div>
    <div v-if="successMessage" class="success-message">{{ successMessage }}</div>

    <!-- 配置历史模态框 -->
    <div v-if="showHistoryModal" class="modal-overlay" @click.self="showHistoryModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3>配置历史记录</h3>
          <button @click="showHistoryModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="configHistory.length === 0" class="empty-state">暂无历史记录</div>
          <div v-else class="history-list">
            <div v-for="history in configHistory" :key="history.id" class="history-item">
              <div class="history-info">
                <span class="history-time">{{ formatTime(history.created_at) }}</span>
                <span class="history-user">{{ history.created_by || '系统' }}</span>
                <span class="history-template" v-if="history.template">{{ history.template }}</span>
              </div>
              <div class="history-actions">
                <button @click="compareWithHistory(history)" class="btn-sm">对比</button>
                <button @click="restoreHistory(history)" class="btn-sm btn-primary">恢复</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 配置对比模态框 -->
    <div v-if="showCompareModal" class="modal-overlay" @click.self="showCompareModal = false">
      <div class="modal-content modal-large">
        <div class="modal-header">
          <h3>配置对比</h3>
          <button @click="showCompareModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="compare-controls">
            <select v-model="compareSource" class="form-select">
              <option value="">选择对比源...</option>
              <optgroup label="系统模板">
                <option value="conservative">保守型模板</option>
                <option value="balanced">平衡型模板</option>
                <option value="aggressive">激进型模板</option>
              </optgroup>
              <optgroup label="自定义模板" v-if="customTemplates.length > 0">
                <option v-for="tpl in customTemplates" :key="tpl.id" :value="'custom_' + tpl.id">
                  {{ tpl.name }}
                </option>
              </optgroup>
            </select>
          </div>
          <div v-if="compareData" class="compare-table">
            <table>
              <thead>
                <tr>
                  <th>参数名称</th>
                  <th>当前值</th>
                  <th>对比值</th>
                  <th>差异</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in compareData" :key="item.key" :class="{ 'diff': item.isDifferent }">
                  <td>{{ item.label }}</td>
                  <td>{{ item.current }}{{ item.unit }}</td>
                  <td>{{ item.compare }}{{ item.unit }}</td>
                  <td>
                    <span v-if="item.isDifferent" class="diff-badge">
                      {{ item.diff > 0 ? '+' : '' }}{{ item.diff }}{{ item.unit }}
                    </span>
                    <span v-else class="same-badge">相同</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- 配置文档模态框 -->
    <div v-if="showDocModal" class="modal-overlay" @click.self="showDocModal = false">
      <div class="modal-content modal-large">
        <div class="modal-header">
          <h3>配置参数文档</h3>
          <button @click="showDocModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body doc-content">
          <div class="doc-section">
            <h4>🎯 触发控制组</h4>
            <div class="doc-item">
              <strong>检查间隔 (trigger_check_interval)</strong>
              <p>每次检查点差是否满足触发条件的时间间隔。</p>
              <p class="doc-impact">💡 影响：间隔越短响应越快，但系统负载越高。推荐0.5秒。</p>
              <p class="doc-best-practice">✅ 最佳实践：网络稳定时可设置0.3-0.5秒，网络不稳定时设置0.8-1.0秒。</p>
            </div>
            <div class="doc-item">
              <strong>开仓/平仓触发次数</strong>
              <p>连续满足触发条件的次数，达到后才执行开仓/平仓。</p>
              <p class="doc-impact">💡 影响：次数越多越稳定，但可能错过快速变化的机会。推荐3次。</p>
              <p class="doc-best-practice">✅ 最佳实践：市场波动大时设置4-5次，市场稳定时设置2-3次。</p>
            </div>
          </div>

          <div class="doc-section">
            <h4>📝 订单执行组</h4>
            <div class="doc-item">
              <strong>Binance超时 (binance_timeout)</strong>
              <p>等待Binance订单完成的最长时间。</p>
              <p class="doc-impact">💡 影响：超时时间 = 检查间隔 × 最大重试次数。过短可能导致订单未完成就超时。</p>
              <p class="doc-best-practice">✅ 最佳实践：限价单设置5-10秒，市价单设置2-5秒。</p>
            </div>
            <div class="doc-item">
              <strong>订单检查间隔 (order_check_interval)</strong>
              <p>检查订单状态的时间间隔。</p>
              <p class="doc-impact">💡 影响：间隔越短订单状态更新越及时，但API调用越频繁。</p>
              <p class="doc-best-practice">✅ 最佳实践：设置0.2秒可以平衡及时性和API限流。</p>
            </div>
            <div class="doc-item">
              <strong>MT5成交同步等待 (mt5_deal_sync_wait)</strong>
              <p>等待MT5同步成交数据的时间。</p>
              <p class="doc-impact">💡 影响：等待时间过短可能导致持仓数据不准确。</p>
              <p class="doc-best-practice">✅ 最佳实践：设置3-5秒确保数据同步完成。</p>
            </div>
          </div>

          <div class="doc-section">
            <h4>🔄 流程控制组</h4>
            <div class="doc-item">
              <strong>API防止频繁调用延迟 (api_spam_prevention_delay)</strong>
              <p>多手执行时，每手之间的延迟时间。</p>
              <p class="doc-impact">💡 影响：防止API被限流，但会增加总执行时间。</p>
              <p class="doc-best-practice">✅ 最佳实践：设置3秒可以有效防止限流。</p>
            </div>
            <div class="doc-item">
              <strong>单腿检查延迟</strong>
              <p>检测到单腿后，等待一段时间再次检查是否仍然是单腿。</p>
              <p class="doc-impact">💡 影响：第一次延迟较长，给对手盘时间成交；第二次延迟较短，快速确认。</p>
              <p class="doc-best-practice">✅ 最佳实践：第一次10秒，第二次1秒。</p>
            </div>
          </div>

          <div class="doc-section">
            <h4>🔁 重试配置组</h4>
            <div class="doc-item">
              <strong>API重试次数和延迟</strong>
              <p>API调用失败后的重试策略。</p>
              <p class="doc-impact">💡 影响：总重试时间 = 重试次数 × 重试延迟。过多会导致执行时间过长。</p>
              <p class="doc-best-practice">✅ 最佳实践：重试3次，每次延迟0.5秒。</p>
            </div>
            <div class="doc-item">
              <strong>Binance限价单最大重试次数</strong>
              <p>Binance限价单未成交时的最大重试次数。</p>
              <p class="doc-impact">💡 影响：次数越多越容易成交，但可能在不利价格成交。</p>
              <p class="doc-best-practice">✅ 最佳实践：设置25次，配合0.2秒检查间隔，总时间约5秒。</p>
            </div>
          </div>

          <div class="doc-section">
            <h4>⏱️ 等待延迟组</h4>
            <div class="doc-item">
              <strong>取消订单后等待时间</strong>
              <p>取消订单后，等待一段时间再重新下单。</p>
              <p class="doc-impact">💡 影响：等待时间过短可能导致订单状态未更新；过长会错过机会。</p>
              <p class="doc-best-practice">✅ 最佳实践：未成交等待3秒，部分成交等待2秒。</p>
            </div>
          </div>

          <div class="doc-section">
            <h4>🖥️ 前端交互组</h4>
            <div class="doc-item">
              <strong>状态轮询间隔 (status_polling_interval)</strong>
              <p>前端轮询后端状态的时间间隔。</p>
              <p class="doc-impact">💡 影响：间隔越短状态更新越及时，但服务器负载越高。</p>
              <p class="doc-best-practice">✅ 最佳实践：设置5秒可以平衡及时性和负载。</p>
            </div>
            <div class="doc-item">
              <strong>防抖延迟 (debounce_delay)</strong>
              <p>用户操作后的防抖延迟，防止频繁触发。</p>
              <p class="doc-impact">💡 影响：延迟越短响应越快，但可能频繁触发。</p>
              <p class="doc-best-practice">✅ 最佳实践：设置0.5秒可以有效防抖。</p>
            </div>
          </div>

          <div class="doc-section">
            <h4>⚠️ 常见问题</h4>
            <div class="doc-item">
              <strong>Q: 为什么订单经常超时？</strong>
              <p>A: 检查Binance超时设置是否过短，建议设置5秒以上。同时检查网络连接是否稳定。</p>
            </div>
            <div class="doc-item">
              <strong>Q: 为什么经常出现单腿？</strong>
              <p>A: 可能是MT5成交同步等待时间过短，建议设置3-5秒。或者是点差波动过大，考虑增加触发次数。</p>
            </div>
            <div class="doc-item">
              <strong>Q: 如何提高执行速度？</strong>
              <p>A: 可以减少触发次数、缩短检查间隔、减少重试次数。但要注意稳定性可能下降。</p>
            </div>
            <div class="doc-item">
              <strong>Q: 如何提高稳定性？</strong>
              <p>A: 增加触发次数、延长超时时间、增加重试次数。但执行速度会变慢。</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 另存为模板模态框 -->
    <div v-if="showSaveTemplateModal" class="modal-overlay" @click.self="showSaveTemplateModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3>另存为模板</h3>
          <button @click="showSaveTemplateModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label for="template-name">模板名称</label>
            <input
              id="template-name"
              v-model="newTemplateName"
              type="text"
              class="form-input"
              placeholder="请输入模板名称（例如：高频交易配置）"
              maxlength="50"
            />
          </div>
          <div class="form-group">
            <label for="template-desc">模板描述（可选）</label>
            <textarea
              id="template-desc"
              v-model="newTemplateDesc"
              class="form-textarea"
              placeholder="描述此模板的用途和特点"
              rows="3"
              maxlength="200"
            ></textarea>
          </div>
          <div class="modal-actions">
            <button @click="showSaveTemplateModal = false" class="btn-secondary">取消</button>
            <button @click="saveAsTemplate" class="btn-primary" :disabled="!newTemplateName.trim()">
              保存模板
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 模板管理模态框 -->
    <div v-if="showTemplateModal" class="modal-overlay" @click.self="showTemplateModal = false">
      <div class="modal-content modal-large">
        <div class="modal-header">
          <h3>模板管理</h3>
          <button @click="showTemplateModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="customTemplates.length === 0" class="empty-state">
            暂无自定义模板，点击"💾 另存为"按钮创建模板
          </div>
          <div v-else class="template-list">
            <div v-for="tpl in customTemplates" :key="tpl.id" class="template-item">
              <div class="template-info">
                <h4>{{ tpl.name }}</h4>
                <p v-if="tpl.description" class="template-desc">{{ tpl.description }}</p>
                <span class="template-time">创建于 {{ formatTime(tpl.created_at) }}</span>
              </div>
              <div class="template-actions">
                <button @click="applyCustomTemplate(tpl)" class="btn-sm btn-primary">应用</button>
                <button @click="compareWithTemplate(tpl)" class="btn-sm">对比</button>
                <button @click="deleteTemplate(tpl.id)" class="btn-sm btn-danger">删除</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 隐藏的文件输入用于导入 -->
    <input
      ref="fileInput"
      type="file"
      accept=".json"
      style="display: none"
      @change="handleFileImport"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { useTimingConfigStore } from '@/stores/timingConfig'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'

const props = defineProps({
  strategyType: {
    type: String,
    required: true
  }
})

const timingConfigStore = useTimingConfigStore()
const saving = ref(false)
const error = ref(null)
const successMessage = ref(null)
const configData = ref({})
const currentTemplate = ref('')
const showHistoryModal = ref(false)
const showCompareModal = ref(false)
const showDocModal = ref(false)
const showSaveTemplateModal = ref(false)
const showTemplateModal = ref(false)
const configHistory = ref([])
const compareSource = ref('')
const compareData = ref(null)
const fileInput = ref(null)
const isLocked = ref(false)
const currentConfigId = ref(null)
const customTemplates = ref([])
const newTemplateName = ref('')
const newTemplateDesc = ref('')

const strategyName = computed(() => {
  const names = {
    'reverse_opening': '反向开仓',
    'reverse_closing': '反向平仓',
    'forward_opening': '正向开仓',
    'forward_closing': '正向平仓'
  }
  return names[props.strategyType] || props.strategyType
})

// 配置模板
const templates = {
  conservative: {
    name: '保守型',
    description: '长超时、低频率、多重试，适合网络不稳定环境',
    config: {
      trigger_check_interval: 1.0,
      opening_trigger_count: 5,
      closing_trigger_count: 5,
      binance_timeout: 10.0,
      bybit_timeout: 0.5,
      order_check_interval: 0.5,
      spread_check_interval: 5.0,
      api_spam_prevention_delay: 5.0,
      delayed_single_leg_check_delay: 15.0,
      delayed_single_leg_second_check_delay: 2.0,
      api_retry_times: 5,
      api_retry_delay: 1.0,
      max_binance_limit_retries: 50,
      open_wait_after_cancel_no_trade: 5.0,
      open_wait_after_cancel_part: 3.0,
      close_wait_after_cancel_no_trade: 5.0,
      close_wait_after_cancel_part: 3.0,
      status_polling_interval: 10.0,
      debounce_delay: 1.0
    }
  },
  balanced: {
    name: '平衡型',
    description: '当前默认值，适合大多数场景',
    config: {
      trigger_check_interval: 0.5,
      opening_trigger_count: 3,
      closing_trigger_count: 3,
      binance_timeout: 5.0,
      bybit_timeout: 0.1,
      order_check_interval: 0.2,
      spread_check_interval: 2.0,
      api_spam_prevention_delay: 3.0,
      delayed_single_leg_check_delay: 10.0,
      delayed_single_leg_second_check_delay: 1.0,
      api_retry_times: 3,
      api_retry_delay: 0.5,
      max_binance_limit_retries: 25,
      open_wait_after_cancel_no_trade: 3.0,
      open_wait_after_cancel_part: 2.0,
      close_wait_after_cancel_no_trade: 3.0,
      close_wait_after_cancel_part: 2.0,
      status_polling_interval: 5.0,
      debounce_delay: 0.5
    }
  },
  aggressive: {
    name: '激进型',
    description: '短超时、高频率、少重试，追求速度',
    config: {
      trigger_check_interval: 0.2,
      opening_trigger_count: 1,
      closing_trigger_count: 1,
      binance_timeout: 2.0,
      bybit_timeout: 0.05,
      order_check_interval: 0.1,
      spread_check_interval: 1.0,
      api_spam_prevention_delay: 1.0,
      delayed_single_leg_check_delay: 5.0,
      delayed_single_leg_second_check_delay: 0.5,
      api_retry_times: 1,
      api_retry_delay: 0.2,
      max_binance_limit_retries: 10,
      open_wait_after_cancel_no_trade: 1.0,
      open_wait_after_cancel_part: 0.5,
      close_wait_after_cancel_no_trade: 1.0,
      close_wait_after_cancel_part: 0.5,
      status_polling_interval: 3.0,
      debounce_delay: 0.2
    }
  }
}

// 根据策略类型生成触发控制参数
const getTriggerParams = () => {
  const baseParams = [
    {
      key: 'trigger_check_interval',
      label: '检查间隔',
      value: 0.5,
      unit: '秒',
      step: 0.1,
      min: 0.1,
      max: 10,
      recommended: 0.5
    }
  ]

  // 根据策略类型添加相应的触发次数参数
  if (props.strategyType === 'reverse_opening' || props.strategyType === 'forward_opening') {
    baseParams.push({
      key: 'opening_trigger_count',
      label: '开仓触发次数',
      value: 3,
      unit: '次',
      step: 1,
      min: 1,
      max: 10,
      recommended: 3
    })
  } else if (props.strategyType === 'reverse_closing' || props.strategyType === 'forward_closing') {
    baseParams.push({
      key: 'closing_trigger_count',
      label: '平仓触发次数',
      value: 3,
      unit: '次',
      step: 1,
      min: 1,
      max: 10,
      recommended: 3
    })
  }

  return baseParams
}

// 定义工作流节点和边
const elements = ref([
  // 节点定义
  {
    id: '1',
    type: 'custom',
    position: { x: 100, y: 50 },
    data: {
      id: '1',
      type: 'trigger',
      icon: '🎯',
      label: '触发控制',
      description: '检查点差是否满足触发条件',
      impact: '触发次数越多越稳定，但响应越慢',
      params: getTriggerParams()
    }
  },
  {
    id: '2',
    type: 'custom',
    position: { x: 100, y: 280 },
    data: {
      id: '2',
      type: 'order',
      icon: '📝',
      label: '订单执行',
      description: 'Binance和Bybit订单执行',
      impact: '超时时间 = 检查间隔 × 最大重试次数',
      params: [
        {
          key: 'binance_timeout',
          label: 'Binance超时',
          value: 5.0,
          unit: '秒',
          step: 0.5,
          min: 0.1,
          max: 60,
          recommended: 5.0
        },
        {
          key: 'bybit_timeout',
          label: 'Bybit超时',
          value: 0.1,
          unit: '秒',
          step: 0.01,
          min: 0.01,
          max: 10,
          recommended: 0.1
        },
        {
          key: 'order_check_interval',
          label: '状态检查间隔',
          value: 0.2,
          unit: '秒',
          step: 0.05,
          min: 0.05,
          max: 5,
          recommended: 0.2
        }
      ]
    }
  },
  {
    id: '3',
    type: 'custom',
    position: { x: 500, y: 280 },
    data: {
      id: '3',
      type: 'monitor',
      icon: '👁️',
      label: '点差监控',
      description: '实时监控点差变化',
      impact: '检查频率越高越及时，但API调用越多',
      params: [
        {
          key: 'spread_check_interval',
          label: '检查间隔',
          value: 2.0,
          unit: '秒',
          step: 0.1,
          min: 0.1,
          max: 30,
          recommended: 2.0
        }
      ]
    }
  },
  {
    id: '4',
    type: 'custom',
    position: { x: 100, y: 550 },
    data: {
      id: '4',
      type: 'wait',
      icon: '⏱️',
      label: '执行后等待',
      description: '防止API频繁调用',
      impact: '等待时间影响下一轮执行的间隔',
      params: [
        {
          key: 'api_spam_prevention_delay',
          label: '等待时间',
          value: 3.0,
          unit: '秒',
          step: 0.5,
          min: 0.5,
          max: 30,
          recommended: 3.0
        }
      ]
    }
  },
  {
    id: '5',
    type: 'custom',
    position: { x: 500, y: 550 },
    data: {
      id: '5',
      type: 'check',
      icon: '🔍',
      label: '单腿检查',
      description: '检测单腿成交情况',
      impact: '延迟时间决定何时检查单腿',
      params: [
        {
          key: 'delayed_single_leg_check_delay',
          label: '第一次延迟',
          value: 10.0,
          unit: '秒',
          step: 1,
          min: 1,
          max: 60,
          recommended: 10.0
        },
        {
          key: 'delayed_single_leg_second_check_delay',
          label: '第二次延迟',
          value: 1.0,
          unit: '秒',
          step: 0.1,
          min: 0.1,
          max: 10,
          recommended: 1.0
        }
      ]
    }
  },
  {
    id: '6',
    type: 'custom',
    position: { x: 100, y: 780 },
    data: {
      id: '6',
      type: 'retry',
      icon: '🔄',
      label: '重试配置',
      description: 'API调用失败重试',
      impact: '重试次数越多越可靠，但失败时等待越久',
      params: [
        {
          key: 'api_retry_times',
          label: '重试次数',
          value: 3,
          unit: '次',
          step: 1,
          min: 1,
          max: 10,
          recommended: 3
        },
        {
          key: 'api_retry_delay',
          label: '重试延迟',
          value: 0.5,
          unit: '秒',
          step: 0.1,
          min: 0.1,
          max: 10,
          recommended: 0.5
        },
        {
          key: 'max_binance_limit_retries',
          label: 'Binance限价单重试',
          value: 25,
          unit: '次',
          step: 1,
          min: 5,
          max: 100,
          recommended: 25
        }
      ]
    }
  },
  {
    id: '7',
    type: 'custom',
    position: { x: 500, y: 780 },
    data: {
      id: '7',
      type: 'cancel',
      icon: '❌',
      label: '取消后等待',
      description: '订单取消后的等待时间',
      impact: '等待时间影响重新下单的速度',
      params: [
        {
          key: 'open_wait_after_cancel_no_trade',
          label: '开仓未成交',
          value: 3.0,
          unit: '秒',
          step: 0.5,
          min: 0.5,
          max: 30,
          recommended: 3.0
        },
        {
          key: 'open_wait_after_cancel_part',
          label: '开仓部分成交',
          value: 2.0,
          unit: '秒',
          step: 0.5,
          min: 0.5,
          max: 30,
          recommended: 2.0
        },
        {
          key: 'close_wait_after_cancel_no_trade',
          label: '平仓未成交',
          value: 3.0,
          unit: '秒',
          step: 0.5,
          min: 0.5,
          max: 30,
          recommended: 3.0
        },
        {
          key: 'close_wait_after_cancel_part',
          label: '平仓部分成交',
          value: 2.0,
          unit: '秒',
          step: 0.5,
          min: 0.5,
          max: 30,
          recommended: 2.0
        }
      ]
    }
  },
  {
    id: '8',
    type: 'custom',
    position: { x: 900, y: 280 },
    data: {
      id: '8',
      type: 'frontend',
      icon: '🖥️',
      label: '前端交互',
      description: '前端轮询和防抖配置',
      impact: '轮询频率影响界面更新速度',
      params: [
        {
          key: 'status_polling_interval',
          label: '状态轮询间隔',
          value: 5.0,
          unit: '秒',
          step: 1,
          min: 1,
          max: 30,
          recommended: 5.0
        },
        {
          key: 'debounce_delay',
          label: '防抖延迟',
          value: 0.5,
          unit: '秒',
          step: 0.1,
          min: 0.1,
          max: 2,
          recommended: 0.5
        }
      ]
    }
  },
  // 边定义（连接线）
  { id: 'e1-2', source: '1', target: '2', type: 'smoothstep', animated: true, label: '触发成功' },
  { id: 'e2-3', source: '2', target: '3', type: 'smoothstep', label: '执行中' },
  { id: 'e2-4', source: '2', target: '4', type: 'smoothstep', label: '执行完成' },
  { id: 'e2-5', source: '2', target: '5', type: 'smoothstep', label: '检查单腿' },
  { id: 'e4-1', source: '4', target: '1', type: 'smoothstep', animated: true, label: '下一轮' },
  { id: 'e2-6', source: '2', target: '6', type: 'smoothstep', style: { stroke: '#ff6b6b' }, label: '失败重试' },
  { id: 'e2-7', source: '2', target: '7', type: 'smoothstep', style: { stroke: '#ffa500' }, label: '取消订单' }
])

onMounted(async () => {
  await loadConfig()
  await loadConfigHistory()
  await loadCustomTemplates()
})

// 监听对比源变化
watch(compareSource, async (newValue) => {
  if (newValue) {
    await generateCompareData(null)
  }
})

async function loadConfig() {
  try {
    // 获取有效配置
    const config = await timingConfigStore.fetchEffectiveConfig(props.strategyType)
    configData.value = config

    // 获取配置详情以检查锁定状态
    const configs = await timingConfigStore.fetchConfigs()
    const strategyConfig = configs.find(c =>
      c.config_level === 'strategy_type' && c.strategy_type === props.strategyType
    )

    if (strategyConfig) {
      currentConfigId.value = strategyConfig.id
      isLocked.value = strategyConfig.is_locked || false
      currentTemplate.value = strategyConfig.template || ''
    }

    // 更新节点参数值
    elements.value.forEach(element => {
      if (element.data && element.data.params) {
        element.data.params.forEach(param => {
          if (config[param.key] !== undefined) {
            param.value = config[param.key]
          }
        })
      }
    })
  } catch (err) {
    error.value = '加载配置失败: ' + (err.response?.data?.detail || err.message)
  }
}

// 切换锁定状态
async function toggleLock() {
  if (!currentConfigId.value) {
    error.value = '配置不存在，无法锁定'
    return
  }

  try {
    const newLockState = !isLocked.value

    if (newLockState) {
      // 锁定配置
      if (!confirm('确定要锁定此配置吗？锁定后将无法修改，直到解锁。')) {
        return
      }
    } else {
      // 解锁配置
      if (!confirm('确定要解锁此配置吗？解锁后可以修改配置。')) {
        return
      }
    }

    await timingConfigStore.updateConfig(currentConfigId.value, {
      is_locked: newLockState
    })

    isLocked.value = newLockState
    successMessage.value = newLockState ? '配置已锁定' : '配置已解锁'
    setTimeout(() => {
      successMessage.value = null
    }, 2000)
  } catch (err) {
    error.value = '切换锁定状态失败: ' + (err.response?.data?.detail || err.message)
  }
}

function validateParam(param) {
  param.warning = null
  param.error = null

  if (param.value < param.min || param.value > param.max) {
    param.error = `值必须在 ${param.min}-${param.max} 之间`
    return
  }

  // 检查是否偏离推荐值
  const deviation = Math.abs(param.value - param.recommended) / param.recommended
  if (deviation > 0.5) {
    param.warning = `偏离推荐值较大，可能影响性能`
  }

  // 逻辑验证规则
  validateLogicalConstraints(param)
}

// 增强的逻辑验证规则
function validateLogicalConstraints(param) {
  const key = param.key

  // 1. 订单超时必须大于检查间隔
  if (key === 'binance_timeout') {
    const orderCheckParam = findParam('order_check_interval')
    if (orderCheckParam && param.value < orderCheckParam.value) {
      param.error = 'Binance超时不能小于订单检查间隔'
      return
    }
    // 警告：超时时间过短可能导致订单未完成就超时
    if (param.value < 3.0) {
      param.warning = '超时时间过短，可能导致订单未完成就超时'
    }
  }

  // 2. 点差检查间隔应该大于等于订单检查间隔
  if (key === 'spread_check_interval') {
    const orderCheckParam = findParam('order_check_interval')
    if (orderCheckParam && param.value < orderCheckParam.value) {
      param.warning = '点差检查间隔建议大于等于订单检查间隔'
    }
  }

  // 3. 订单检查间隔不能太小，否则会频繁查询
  if (key === 'order_check_interval') {
    if (param.value < 0.1) {
      param.error = '订单检查间隔过小会导致API频繁调用'
      return
    }
    const binanceTimeout = findParam('binance_timeout')
    if (binanceTimeout && param.value > binanceTimeout.value) {
      param.error = '订单检查间隔不能大于Binance超时时间'
    }
  }

  // 4. API防止频繁调用延迟应该合理
  if (key === 'api_spam_prevention_delay') {
    if (param.value < 1.0) {
      param.warning = '延迟过短可能导致API被限流'
    }
    if (param.value > 10.0) {
      param.warning = '延迟过长会影响执行速度'
    }
  }

  // 5. 单腿检查延迟逻辑
  if (key === 'delayed_single_leg_check_delay') {
    const secondCheck = findParam('delayed_single_leg_second_check_delay')
    if (secondCheck && param.value < secondCheck.value) {
      param.error = '第一次检查延迟应该大于第二次检查延迟'
    }
  }

  if (key === 'delayed_single_leg_second_check_delay') {
    const firstCheck = findParam('delayed_single_leg_check_delay')
    if (firstCheck && param.value > firstCheck.value) {
      param.error = '第二次检查延迟应该小于第一次检查延迟'
    }
  }

  // 6. 重试配置验证
  if (key === 'api_retry_times') {
    if (param.value > 5) {
      param.warning = '重试次数过多可能导致执行时间过长'
    }
  }

  if (key === 'api_retry_delay') {
    const retryTimes = findParam('api_retry_times')
    if (retryTimes && param.value * retryTimes.value > 10) {
      param.warning = `总重试时间 (${(param.value * retryTimes.value).toFixed(1)}秒) 过长`
    }
  }

  // 7. 触发检查间隔验证
  if (key === 'trigger_check_interval') {
    if (param.value < 0.2) {
      param.warning = '检查间隔过短会增加系统负载'
    }
    if (param.value > 2.0) {
      param.warning = '检查间隔过长可能错过交易机会'
    }
  }

  // 8. 触发次数验证
  if (key === 'opening_trigger_count' || key === 'closing_trigger_count') {
    const triggerInterval = findParam('trigger_check_interval')
    if (triggerInterval && param.value * triggerInterval.value > 5) {
      param.warning = `总触发时间 (${(param.value * triggerInterval.value).toFixed(1)}秒) 过长，可能错过机会`
    }
  }

  // 9. MT5成交同步等待验证
  if (key === 'mt5_deal_sync_wait') {
    if (param.value < 1.0) {
      param.warning = '等待时间过短，MT5可能还未同步成交数据'
    }
    if (param.value > 10.0) {
      param.warning = '等待时间过长会影响执行效率'
    }
  }

  // 10. 取消订单后等待时间验证
  if (key.includes('wait_after_cancel')) {
    if (param.value < 1.0) {
      param.warning = '等待时间过短可能导致订单状态未更新'
    }
    if (param.value > 10.0) {
      param.warning = '等待时间过长会影响重新下单速度'
    }
  }

  // 11. 前端交互参数验证
  if (key === 'status_polling_interval') {
    if (param.value < 2.0) {
      param.warning = '轮询间隔过短会增加服务器负载'
    }
    if (param.value > 15.0) {
      param.warning = '轮询间隔过长，状态更新不及时'
    }
  }

  if (key === 'debounce_delay') {
    if (param.value < 0.2) {
      param.warning = '防抖延迟过短可能导致频繁触发'
    }
    if (param.value > 1.0) {
      param.warning = '防抖延迟过长会影响响应速度'
    }
  }
}

function findParam(key) {
  for (const element of elements.value) {
    if (element.data && element.data.params) {
      const param = element.data.params.find(p => p.key === key)
      if (param) return param
    }
  }
  return null
}

function onParamChange(nodeId, paramKey, value) {
  configData.value[paramKey] = value
  currentTemplate.value = '' // 手动修改后清除模板标记
}

// 一键应用模板
function applyTemplateByKey(templateKey) {
  const template = templates[templateKey]
  if (!template) return

  if (!confirm(`确定要应用${template.name}配置吗？这将覆盖当前所有参数。`)) {
    return
  }

  // 应用模板配置到所有节点
  elements.value.forEach(element => {
    if (element.data && element.data.params) {
      element.data.params.forEach(param => {
        if (template.config[param.key] !== undefined) {
          param.value = template.config[param.key]
          configData.value[param.key] = param.value
          validateParam(param)
        }
      })
    }
  })

  currentTemplate.value = templateKey
  successMessage.value = `已应用${template.name}配置模板`
  setTimeout(() => {
    successMessage.value = null
  }, 2000)
}

// 导出配置
function exportConfig() {
  const exportData = {
    strategy_type: props.strategyType,
    strategy_name: strategyName.value,
    template: currentTemplate.value,
    timestamp: new Date().toISOString(),
    config: {}
  }

  // 收集所有参数
  elements.value.forEach(element => {
    if (element.data && element.data.params) {
      element.data.params.forEach(param => {
        exportData.config[param.key] = param.value
      })
    }
  })

  // 创建下载
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `timing_config_${props.strategyType}_${Date.now()}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)

  successMessage.value = '配置已导出'
  setTimeout(() => {
    successMessage.value = null
  }, 2000)
}

// 导入配置
function importConfig() {
  fileInput.value.click()
}

function handleFileImport(event) {
  const file = event.target.files[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const importData = JSON.parse(e.target.result)

      if (!importData.config) {
        throw new Error('无效的配置文件格式')
      }

      if (!confirm(`确定要导入配置吗？这将覆盖当前所有参数。\n\n来源: ${importData.strategy_name || '未知'}\n时间: ${importData.timestamp || '未知'}`)) {
        return
      }

      // 应用导入的配置
      elements.value.forEach(element => {
        if (element.data && element.data.params) {
          element.data.params.forEach(param => {
            if (importData.config[param.key] !== undefined) {
              param.value = importData.config[param.key]
              configData.value[param.key] = param.value
              validateParam(param)
            }
          })
        }
      })

      currentTemplate.value = importData.template || ''
      successMessage.value = '配置已导入'
      setTimeout(() => {
        successMessage.value = null
      }, 2000)
    } catch (err) {
      error.value = '导入失败: ' + err.message
    }
  }
  reader.readAsText(file)

  // 重置文件输入
  event.target.value = ''
}

// 加载配置历史
async function loadConfigHistory() {
  try {
    const response = await timingConfigStore.fetchConfigHistory(props.strategyType)
    configHistory.value = response || []
  } catch (err) {
    console.error('加载历史失败:', err)
  }
}

// 恢复历史配置
function restoreHistory(history) {
  if (!confirm(`确定要恢复到 ${formatTime(history.created_at)} 的配置吗？`)) {
    return
  }

  // 应用历史配置
  elements.value.forEach(element => {
    if (element.data && element.data.params) {
      element.data.params.forEach(param => {
        if (history.config[param.key] !== undefined) {
          param.value = history.config[param.key]
          configData.value[param.key] = param.value
          validateParam(param)
        }
      })
    }
  })

  currentTemplate.value = history.template || ''
  showHistoryModal.value = false
  successMessage.value = '已恢复历史配置'
  setTimeout(() => {
    successMessage.value = null
  }, 2000)
}

// 对比历史配置
function compareWithHistory(history) {
  compareSource.value = 'history_' + history.id
  generateCompareData(history.config)
  showHistoryModal.value = false
  showCompareModal.value = true
}

// 生成对比数据
async function generateCompareData(compareConfig) {
  if (!compareConfig) {
    // 根据compareSource加载配置
    if (compareSource.value.startsWith('history_')) {
      return
    } else if (compareSource.value.startsWith('custom_')) {
      // 加载自定义模板
      const templateId = parseInt(compareSource.value.replace('custom_', ''))
      const template = customTemplates.value.find(t => t.id === templateId)
      if (template) {
        compareConfig = template.config_data
      } else {
        error.value = '自定义模板不存在'
        return
      }
    } else if (templates[compareSource.value]) {
      compareConfig = templates[compareSource.value].config
    } else {
      error.value = '无效的对比源'
      return
    }
  }

  const data = []
  const paramLabels = {}

  // 收集参数标签
  elements.value.forEach(element => {
    if (element.data && element.data.params) {
      element.data.params.forEach(param => {
        paramLabels[param.key] = {
          label: param.label,
          unit: param.unit
        }
      })
    }
  })

  // 生成对比数据
  Object.keys(compareConfig).forEach(key => {
    const current = configData.value[key]
    const compare = compareConfig[key]

    if (current !== undefined && paramLabels[key]) {
      const isDifferent = current !== compare
      data.push({
        key,
        label: paramLabels[key].label,
        unit: paramLabels[key].unit,
        current,
        compare,
        diff: isDifferent ? (current - compare) : 0,
        isDifferent
      })
    }
  })

  compareData.value = data
}

// 加载自定义模板
async function loadCustomTemplates() {
  try {
    const response = await timingConfigStore.fetchCustomTemplates(props.strategyType)
    customTemplates.value = response || []
  } catch (err) {
    console.error('加载自定义模板失败:', err)
  }
}

// 另存为模板
async function saveAsTemplate() {
  if (!newTemplateName.value.trim()) {
    error.value = '请输入模板名称'
    return
  }

  try {
    // 收集当前配置
    const configToSave = {}
    elements.value.forEach(element => {
      if (element.data && element.data.params) {
        element.data.params.forEach(param => {
          configToSave[param.key] = param.value
        })
      }
    })

    await timingConfigStore.createCustomTemplate({
      strategy_type: props.strategyType,
      name: newTemplateName.value.trim(),
      description: newTemplateDesc.value.trim() || null,
      config_data: configToSave
    })

    // 重新加载模板列表
    await loadCustomTemplates()

    // 关闭模态框并重置表单
    showSaveTemplateModal.value = false
    newTemplateName.value = ''
    newTemplateDesc.value = ''

    successMessage.value = '模板保存成功'
    setTimeout(() => {
      successMessage.value = null
    }, 2000)
  } catch (err) {
    error.value = '保存模板失败: ' + (err.response?.data?.detail || err.message)
  }
}

// 应用自定义模板
function applyCustomTemplate(template) {
  if (!confirm(`确定要应用模板"${template.name}"吗？这将覆盖当前所有参数。`)) {
    return
  }

  // 应用模板配置到所有节点
  elements.value.forEach(element => {
    if (element.data && element.data.params) {
      element.data.params.forEach(param => {
        if (template.config_data[param.key] !== undefined) {
          param.value = template.config_data[param.key]
          configData.value[param.key] = param.value
          validateParam(param)
        }
      })
    }
  })

  currentTemplate.value = 'custom_' + template.id
  showTemplateModal.value = false
  successMessage.value = `已应用模板"${template.name}"`
  setTimeout(() => {
    successMessage.value = null
  }, 2000)
}

// 对比自定义模板
function compareWithTemplate(template) {
  compareSource.value = 'custom_' + template.id
  showTemplateModal.value = false
  showCompareModal.value = true
}

// 删除自定义模板
async function deleteTemplate(templateId) {
  const template = customTemplates.value.find(t => t.id === templateId)
  if (!template) return

  if (!confirm(`确定要删除模板"${template.name}"吗？此操作不可恢复。`)) {
    return
  }

  try {
    await timingConfigStore.deleteCustomTemplate(templateId)
    await loadCustomTemplates()

    successMessage.value = '模板已删除'
    setTimeout(() => {
      successMessage.value = null
    }, 2000)
  } catch (err) {
    error.value = '删除模板失败: ' + (err.response?.data?.detail || err.message)
  }
}

// 格式化时间
function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN')
}

// 获取策略名称
function getStrategyName(type) {
  const names = {
    'reverse_opening': '反向开仓',
    'reverse_closing': '反向平仓',
    'forward_opening': '正向开仓',
    'forward_closing': '正向平仓'
  }
  return names[type] || type
}

async function saveConfig() {
  saving.value = true
  error.value = null
  successMessage.value = null

  try {
    // 验证所有参数
    let hasError = false
    elements.value.forEach(element => {
      if (element.data && element.data.params) {
        element.data.params.forEach(param => {
          validateParam(param)
          if (param.error) hasError = true
        })
      }
    })

    if (hasError) {
      error.value = '配置验证失败，请检查标红的参数'
      return
    }

    // 收集所有参数
    const updateData = {
      template: currentTemplate.value // 保存当前使用的模板
    }
    elements.value.forEach(element => {
      if (element.data && element.data.params) {
        element.data.params.forEach(param => {
          updateData[param.key] = param.value
        })
      }
    })

    // 查找或创建配置
    const configs = await timingConfigStore.fetchConfigs()
    const existingConfig = configs.find(c =>
      c.config_level === 'strategy_type' && c.strategy_type === props.strategyType
    )

    if (existingConfig) {
      await timingConfigStore.updateConfig(existingConfig.id, updateData)
    } else {
      await timingConfigStore.createConfig({
        config_level: 'strategy_type',
        strategy_type: props.strategyType,
        ...updateData
      })
    }

    // 重新加载历史记录
    await loadConfigHistory()

    successMessage.value = '配置保存成功！'
    setTimeout(() => {
      successMessage.value = null
    }, 3000)
  } catch (err) {
    error.value = '保存失败: ' + (err.response?.data?.detail || err.message)
  } finally {
    saving.value = false
  }
}

async function resetConfig() {
  if (!confirm('确定要重置为默认值吗？')) return

  // 应用平衡型模板
  const template = templates.balanced
  elements.value.forEach(element => {
    if (element.data && element.data.params) {
      element.data.params.forEach(param => {
        if (template.config[param.key] !== undefined) {
          param.value = template.config[param.key]
          param.warning = null
          param.error = null
        }
      })
    }
  })
}
</script>

<style scoped>
.workflow-canvas {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #1a1d23;
}

.canvas-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  background: #252930;
  border-bottom: 1px solid #2d3139;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.canvas-header h2 {
  margin: 0;
  font-size: 16px;
  color: #e0e0e0;
}

.lock-badge {
  display: inline-block;
  padding: 4px 12px;
  background: #ff9800;
  color: white;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.template-group {
  display: flex;
  gap: 8px;
  padding: 4px;
  background: #1a1d23;
  border-radius: 6px;
}

.btn-template {
  padding: 8px 16px;
  background: #2d3139;
  border: 1px solid #3d4451;
  border-radius: 4px;
  color: #e0e0e0;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-template:hover {
  background: #3d4451;
  border-color: #4CAF50;
}

.btn-template.active {
  background: #4CAF50;
  border-color: #4CAF50;
  color: white;
  font-weight: 500;
}

.action-buttons {
  display: flex;
  gap: 8px;
}

.template-select {
  padding: 8px 12px;
  background: #1a1d23;
  border: 1px solid #3d4451;
  border-radius: 4px;
  color: #e0e0e0;
  font-size: 14px;
  cursor: pointer;
}

.template-select:focus {
  outline: none;
  border-color: #4CAF50;
}

.workflow-flow {
  flex: 1;
  background: #1a1d23;
}

.custom-node {
  background: #252930;
  border: 2px solid #3d4451;
  border-radius: 8px;
  padding: 12px;
  min-width: 300px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
}

.custom-node.trigger {
  border-color: #4CAF50;
}

.custom-node.order {
  border-color: #2196F3;
}

.custom-node.monitor {
  border-color: #FF9800;
}

.custom-node.wait {
  border-color: #9C27B0;
}

.custom-node.check {
  border-color: #00BCD4;
}

.custom-node.retry {
  border-color: #FFC107;
}

.custom-node.cancel {
  border-color: #F44336;
}

.custom-node.frontend {
  border-color: #E91E63;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #3d4451;
}

.node-icon {
  font-size: 20px;
}

.node-title {
  font-weight: 600;
  font-size: 14px;
  color: #e0e0e0;
}

.node-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.param-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-row label {
  font-size: 12px;
  color: #a0a0a0;
}

.param-input {
  display: flex;
  align-items: center;
  gap: 6px;
}

.param-input input {
  flex: 1;
  padding: 6px 8px;
  background: #1a1d23;
  border: 1px solid #3d4451;
  border-radius: 4px;
  color: #e0e0e0;
  font-size: 13px;
}

.param-input input:focus {
  outline: none;
  border-color: #4CAF50;
}

.param-input input.warning {
  border-color: #FFC107;
}

.param-input input.error {
  border-color: #F44336;
}

.param-unit {
  font-size: 12px;
  color: #808080;
  min-width: 30px;
}

.param-hint {
  font-size: 11px;
  color: #606060;
}

.param-hint.text-warning {
  color: #FFC107;
}

.param-hint.text-error {
  color: #F44336;
}

.node-description {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #3d4451;
  font-size: 11px;
  color: #808080;
}

.node-impact {
  margin-top: 6px;
  padding: 6px 8px;
  background: rgba(76, 175, 80, 0.1);
  border-left: 3px solid #4CAF50;
  font-size: 11px;
  color: #a0a0a0;
  border-radius: 2px;
}

.btn-primary {
  padding: 8px 16px;
  background-color: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.btn-primary:hover:not(:disabled) {
  background-color: #45a049;
}

.btn-primary:disabled {
  background-color: #666;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 8px 16px;
  background-color: #555;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.btn-secondary:hover {
  background-color: #666;
}

.error-message {
  position: fixed;
  bottom: 20px;
  right: 20px;
  padding: 12px 20px;
  background-color: #f44336;
  color: white;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  z-index: 1000;
  max-width: 400px;
}

.success-message {
  position: fixed;
  bottom: 20px;
  right: 20px;
  padding: 12px 20px;
  background-color: #4CAF50;
  color: white;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  z-index: 1000;
}

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.modal-content {
  background: #252930;
  border-radius: 8px;
  width: 90%;
  max-width: 600px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
}

.modal-content.modal-large {
  max-width: 900px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #3d4451;
}

.modal-header h3 {
  margin: 0;
  color: #e0e0e0;
  font-size: 18px;
}

.btn-close {
  background: none;
  border: none;
  color: #999;
  font-size: 24px;
  cursor: pointer;
  padding: 0;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close:hover {
  color: #fff;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: #999;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: #1a1d23;
  border: 1px solid #3d4451;
  border-radius: 6px;
}

.history-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.history-time {
  color: #e0e0e0;
  font-size: 14px;
}

.history-user {
  color: #999;
  font-size: 12px;
}

.history-template {
  display: inline-block;
  padding: 2px 8px;
  background: #4CAF50;
  color: white;
  border-radius: 3px;
  font-size: 11px;
  margin-top: 4px;
}

.history-actions {
  display: flex;
  gap: 8px;
}

.btn-sm {
  padding: 6px 12px;
  background: #3d4451;
  color: #e0e0e0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.btn-sm:hover {
  background: #4d5461;
}

.btn-sm.btn-primary {
  background: #4CAF50;
}

.btn-sm.btn-primary:hover {
  background: #45a049;
}

.compare-controls {
  margin-bottom: 20px;
}

.form-select {
  width: 100%;
  padding: 10px;
  background: #1a1d23;
  border: 1px solid #3d4451;
  border-radius: 4px;
  color: #e0e0e0;
  font-size: 14px;
}

.form-select:focus {
  outline: none;
  border-color: #4CAF50;
}

.compare-table {
  overflow-x: auto;
}

.compare-table table {
  width: 100%;
  border-collapse: collapse;
}

.compare-table th,
.compare-table td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid #3d4451;
}

.compare-table th {
  background: #1a1d23;
  color: #e0e0e0;
  font-weight: 500;
  font-size: 13px;
}

.compare-table td {
  color: #ccc;
  font-size: 14px;
}

.compare-table tr.diff {
  background: rgba(255, 152, 0, 0.1);
}

.diff-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #FF9800;
  color: white;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
}

.same-badge {
  color: #4CAF50;
  font-size: 12px;
}

/* 文档模态框样式 */
.doc-content {
  max-height: 70vh;
  overflow-y: auto;
}

.doc-section {
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 1px solid #3d4451;
}

.doc-section:last-child {
  border-bottom: none;
}

.doc-section h4 {
  margin: 0 0 16px 0;
  color: #4CAF50;
  font-size: 16px;
}

.doc-item {
  margin-bottom: 20px;
  padding: 12px;
  background: #1a1d23;
  border-radius: 6px;
}

.doc-item:last-child {
  margin-bottom: 0;
}

.doc-item strong {
  display: block;
  margin-bottom: 8px;
  color: #e0e0e0;
  font-size: 14px;
}

.doc-item p {
  margin: 6px 0;
  color: #ccc;
  font-size: 13px;
  line-height: 1.6;
}

.doc-impact {
  color: #FF9800 !important;
  font-style: italic;
}

.doc-best-practice {
  color: #4CAF50 !important;
  font-weight: 500;
}

/* 禁用状态样式 */
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-template:disabled {
  background: #2d3139;
  border-color: #3d4451;
  cursor: not-allowed;
}

.btn-template:disabled:hover {
  background: #2d3139;
  border-color: #3d4451;
}

/* 表单样式 */
.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  color: #e0e0e0;
  font-size: 14px;
  font-weight: 500;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 10px;
  background: #1a1d23;
  border: 1px solid #3d4451;
  border-radius: 4px;
  color: #e0e0e0;
  font-size: 14px;
  font-family: inherit;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: #4CAF50;
}

.form-textarea {
  resize: vertical;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #3d4451;
}

/* 模板列表样式 */
.template-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.template-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 16px;
  background: #1a1d23;
  border: 1px solid #3d4451;
  border-radius: 6px;
  transition: border-color 0.2s;
}

.template-item:hover {
  border-color: #4CAF50;
}

.template-info {
  flex: 1;
}

.template-info h4 {
  margin: 0 0 8px 0;
  color: #e0e0e0;
  font-size: 16px;
}

.template-desc {
  margin: 0 0 8px 0;
  color: #999;
  font-size: 13px;
  line-height: 1.5;
}

.template-time {
  color: #666;
  font-size: 12px;
}

.template-actions {
  display: flex;
  gap: 8px;
  margin-left: 16px;
}

.btn-danger {
  background: #f44336;
  color: white;
}

.btn-danger:hover {
  background: #d32f2f;
}
</style>
