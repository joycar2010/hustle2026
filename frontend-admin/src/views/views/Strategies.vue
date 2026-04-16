<template>
  <div class="strategies-page">

    <!-- 策略类型选择卡 -->
    <div class="type-selector">
      <div
        v-for="t in strategyTypes" :key="t.type"
        @click="switchStrategy(t.type)"
        :class="['type-card', activeType === t.type && 'active']"
      >
        <span class="type-icon">{{ t.icon }}</span>
        <span class="type-label">{{ t.label }}</span>
      </div>
    </div>

    <!-- ── VueFlow 工作流画布 ── -->
    <div class="workflow-canvas">
      <div class="canvas-header">
        <div class="header-left">
          <h2>{{ strategyName }} - 执行流程配置</h2>
          <span v-if="isLocked" class="lock-badge">🔒 已锁定</span>
        </div>
        <div class="header-actions">
          <div class="template-group">
            <button
              v-for="(tpl, key) in builtinTemplates" :key="key"
              @click="applyTemplateByKey(key)"
              :class="['btn-template', { active: currentTemplate === key }]"
              :disabled="isLocked"
            >{{ tpl.name }}</button>
          </div>
          <div class="action-buttons">
            <button @click="showDocModal = true" class="btn-secondary">📖 文档</button>
            <button @click="openTemplateModal" class="btn-secondary">📋 模板</button>
            <button @click="openHistoryModal" class="btn-secondary">📜 历史</button>
            <button @click="exportConfig" class="btn-secondary">📤 导出</button>
            <button @click="importConfig" class="btn-secondary" :disabled="isLocked">📥 导入</button>
            <button @click="showCompareModal = true" class="btn-secondary">🔍 对比</button>
            <button @click="showSaveTemplateModal = true" class="btn-secondary">💾 另存为</button>
            <button @click="toggleLock" class="btn-secondary">{{ isLocked ? '🔓 解锁' : '🔒 锁定' }}</button>
            <button @click="saveWorkflowConfig" class="btn-primary" :disabled="saving || isLocked">
              {{ saving ? '保存中...' : '💾 保存配置' }}
            </button>
            <button @click="resetConfig" class="btn-secondary" :disabled="isLocked">🔄 重置</button>
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
                    type="number"
                    :step="param.step"
                    :min="param.min"
                    :max="param.max"
                    @input="validateParam(param)"
                    @change="onParamChange(data.id, param.key, param.value)"
                    :class="{ warning: param.warning, error: param.error }"
                  />
                  <span class="param-unit">{{ param.unit }}</span>
                </div>
                <span class="param-hint" :class="{ 'text-warning': param.warning, 'text-error': param.error }">
                  {{ param.warning || param.error || `推荐: ${param.recommended}${param.unit}` }}
                </span>
              </div>
            </div>
            <div v-if="data.description" class="node-description">{{ data.description }}</div>
            <div v-if="data.impact" class="node-impact">💡 {{ data.impact }}</div>
          </div>
        </template>
      </VueFlow>

      <div v-if="canvasError" class="error-message">{{ canvasError }}</div>
      <div v-if="successMessage" class="success-message">{{ successMessage }}</div>
    </div>

    <!-- ── 配置记录 CRUD（可折叠） ── -->
    <div class="crud-section">
      <div class="crud-header" @click="crudOpen = !crudOpen">
        <span class="font-semibold text-sm">timing-configs 配置记录</span>
        <span class="text-xs text-text-tertiary">{{ crudOpen ? '▲ 收起' : '▼ 展开' }}</span>
      </div>
      <template v-if="crudOpen">
        <!-- 有效配置 -->
        <div v-if="effectiveConfig" class="effective-bar">
          <div class="flex items-center gap-2 mb-2">
            <div class="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
            <span class="text-sm font-bold text-primary">当前有效配置</span>
            <span class="text-xs text-text-tertiary">{{ effectiveConfig.config_name || effectiveConfig.name }}</span>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div v-for="f in configFields" :key="f.key">
              <div class="text-text-tertiary mb-0.5">{{ f.label }}</div>
              <div class="font-mono font-semibold">{{ effectiveConfig[f.key] ?? '--' }}{{ f.unit ?? '' }}</div>
            </div>
          </div>
        </div>
        <div v-else class="py-3 text-center text-xs text-text-tertiary">
          {{ loadingEffective ? '加载中...' : '当前策略类型暂无有效配置' }}
        </div>

        <!-- 操作栏 -->
        <div class="crud-toolbar">
          <button @click="reloadConfigs" :disabled="reloading" class="btn-sm-outline">
            {{ reloading ? '重载中...' : '↻ 重载配置' }}
          </button>
          <button @click="openCreateModal" class="btn-sm-primary">+ 新增配置</button>
        </div>

        <!-- 配置列表 -->
        <div v-if="loading" class="py-8 text-center text-text-tertiary text-sm">加载中...</div>
        <div v-else-if="!typeConfigs.length" class="py-8 text-center text-text-tertiary text-sm">暂无配置</div>
        <div v-else class="config-list">
          <div v-for="cfg in typeConfigs" :key="cfg.id" class="config-row">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1 flex-wrap">
                <span class="font-semibold text-sm">{{ cfg.config_name || cfg.name }}</span>
                <span class="badge-level">{{ cfg.config_level || cfg.level }}</span>
                <span v-if="cfg.is_active || cfg.is_effective" class="badge-active">生效中</span>
                <span v-if="cfg.enabled === false" class="badge-disabled">已禁用</span>
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-0.5 text-xs text-text-tertiary">
                <div v-for="f in configFields" :key="f.key">
                  {{ f.label }}：<span class="font-mono text-text-secondary">{{ cfg[f.key] ?? '--' }}{{ f.unit ?? '' }}</span>
                </div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              <button @click="openEditModal(cfg)" class="btn-xs">编辑</button>
              <button @click="openCrudHistoryModal(cfg)" class="btn-xs">历史</button>
              <button @click="deleteConfig(cfg)" class="btn-xs danger">删除</button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ── 配置历史模态框（画布） ── -->
    <div v-if="showHistoryModal" class="modal-overlay" @click.self="showHistoryModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3>配置历史记录</h3>
          <button @click="showHistoryModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="!configHistory.length" class="empty-state">暂无历史记录</div>
          <div v-else class="history-list">
            <div v-for="h in configHistory" :key="h.id" class="history-item">
              <div class="history-info">
                <span class="history-time">{{ formatTime(h.created_at) }}</span>
                <span class="history-user">{{ h.created_by || '系统' }}</span>
                <span class="history-template" v-if="h.template">{{ h.template }}</span>
              </div>
              <div class="history-actions">
                <button @click="compareWithHistory(h)" class="btn-sm">对比</button>
                <button @click="restoreHistory(h)" class="btn-sm btn-primary">恢复</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 对比模态框 ── -->
    <div v-if="showCompareModal" class="modal-overlay" @click.self="showCompareModal = false">
      <div class="modal-content modal-large">
        <div class="modal-header">
          <h3>配置对比</h3>
          <button @click="showCompareModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="compare-controls">
            <select v-model="compareSource" class="form-select" @change="generateCompareData(null)">
              <option value="">选择对比源...</option>
              <optgroup label="系统模板">
                <option value="conservative">保守型模板</option>
                <option value="balanced">平衡型模板</option>
                <option value="aggressive">激进型模板</option>
              </optgroup>
              <optgroup label="自定义模板" v-if="customTemplates.length">
                <option v-for="tpl in customTemplates" :key="tpl.id" :value="'custom_' + tpl.id">{{ tpl.name }}</option>
              </optgroup>
            </select>
          </div>
          <div v-if="compareData" class="compare-table">
            <table>
              <thead>
                <tr><th>参数名称</th><th>当前值</th><th>对比值</th><th>差异</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in compareData" :key="item.key" :class="{ diff: item.isDifferent }">
                  <td>{{ item.label }}</td>
                  <td>{{ item.current }}{{ item.unit }}</td>
                  <td>{{ item.compare }}{{ item.unit }}</td>
                  <td>
                    <span v-if="item.isDifferent" class="diff-badge">{{ item.diff > 0 ? '+' : '' }}{{ item.diff }}{{ item.unit }}</span>
                    <span v-else class="same-badge">相同</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 文档模态框 ── -->
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
              <p class="doc-impact">💡 间隔越短响应越快，但系统负载越高。推荐0.5秒。</p>
            </div>
            <div class="doc-item">
              <strong>开仓/平仓触发次数</strong>
              <p>连续满足触发条件的次数，达到后才执行开仓/平仓。</p>
              <p class="doc-impact">💡 次数越多越稳定，但可能错过快速变化的机会。推荐3次。</p>
            </div>
          </div>
          <div class="doc-section">
            <h4>📝 订单执行组</h4>
            <div class="doc-item">
              <strong>Binance超时 (binance_timeout)</strong>
              <p>等待Binance订单完成的最长时间。超时时间 = 检查间隔 × 最大重试次数。</p>
              <p class="doc-impact">💡 限价单设置5-10秒，市价单设置2-5秒。</p>
            </div>
            <div class="doc-item">
              <strong>MT5成交同步等待 (mt5_deal_sync_wait)</strong>
              <p>等待MT5同步成交数据的时间，设置3-5秒确保数据同步完成。</p>
            </div>
          </div>
          <div class="doc-section">
            <h4>🔄 流程控制组</h4>
            <div class="doc-item">
              <strong>API防止频繁调用延迟 (api_spam_prevention_delay)</strong>
              <p>多手执行时，每手之间的延迟时间。设置3秒可以有效防止限流。</p>
            </div>
            <div class="doc-item">
              <strong>单腿检查延迟</strong>
              <p>检测到单腿后，等待一段时间再次检查。第一次10秒，第二次1秒。</p>
            </div>
          </div>
          <div class="doc-section">
            <h4>⚠️ 常见问题</h4>
            <div class="doc-item"><strong>Q: 为什么订单经常超时？</strong><p>A: 检查Binance超时设置是否过短，建议5秒以上。</p></div>
            <div class="doc-item"><strong>Q: 为什么经常出现单腿？</strong><p>A: MT5成交同步等待时间过短，建议设置3-5秒。</p></div>
            <div class="doc-item"><strong>Q: 如何提高执行速度？</strong><p>A: 减少触发次数、缩短检查间隔、减少重试次数。</p></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 另存为模板 ── -->
    <div v-if="showSaveTemplateModal" class="modal-overlay" @click.self="showSaveTemplateModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3>另存为模板</h3>
          <button @click="showSaveTemplateModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>模板名称</label>
            <input v-model="newTemplateName" type="text" class="form-input" placeholder="请输入模板名称" maxlength="50" />
          </div>
          <div class="form-group">
            <label>模板描述（可选）</label>
            <textarea v-model="newTemplateDesc" class="form-textarea" placeholder="描述此模板的用途" rows="3" maxlength="200"></textarea>
          </div>
          <div class="modal-actions">
            <button @click="showSaveTemplateModal = false" class="btn-secondary">取消</button>
            <button @click="saveAsTemplate" class="btn-primary" :disabled="!newTemplateName.trim()">保存模板</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 模板管理 ── -->
    <div v-if="showTemplateModal" class="modal-overlay" @click.self="showTemplateModal = false">
      <div class="modal-content modal-large">
        <div class="modal-header">
          <h3>模板管理</h3>
          <button @click="showTemplateModal = false" class="btn-close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="!customTemplates.length" class="empty-state">暂无自定义模板，点击"💾 另存为"创建</div>
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
                <button @click="deleteCustomTemplate(tpl.id)" class="btn-sm btn-danger">删除</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 新增/编辑 CRUD Modal ── -->
    <Teleport to="body">
      <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
        <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
          <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
            <h3 class="font-bold text-lg">{{ editingConfig ? '编辑配置' : '新增配置' }}</h3>
            <button @click="showModal = false" class="text-text-tertiary hover:text-text-primary text-xl">✕</button>
          </div>
          <div class="p-6 space-y-4">
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-xs text-text-tertiary mb-1.5">配置名称 *</label>
                <input v-model="form.config_name" placeholder="如：激进模式" class="input-field w-full" />
              </div>
              <div>
                <label class="block text-xs text-text-tertiary mb-1.5">配置层级</label>
                <select v-model="form.config_level" class="input-field w-full">
                  <option value="global">全局 (global)</option>
                  <option value="strategy_type">策略类型 (strategy_type)</option>
                  <option value="instance">实例 (instance)</option>
                </select>
              </div>
              <div>
                <label class="block text-xs text-text-tertiary mb-1.5">策略类型</label>
                <select v-model="form.strategy_type" class="input-field w-full">
                  <option v-for="t in strategyTypes" :key="t.type" :value="t.type">{{ t.label }}</option>
                </select>
              </div>
              <div class="flex items-end pb-0.5">
                <label class="flex items-center gap-2 cursor-pointer">
                  <div @click="form.enabled = !form.enabled"
                    :class="['w-10 h-5 rounded-full transition-colors cursor-pointer relative', form.enabled ? 'bg-primary' : 'bg-gray-600']">
                    <span :class="['absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', form.enabled ? 'translate-x-5' : 'translate-x-0.5']" />
                  </div>
                  <span class="text-sm">{{ form.enabled ? '已启用' : '已禁用' }}</span>
                </label>
              </div>
            </div>
            <div class="bg-dark-200 rounded-xl p-4 space-y-3">
              <div class="text-xs font-bold text-text-secondary mb-2">核心参数</div>
              <div class="grid grid-cols-2 gap-4">
                <div v-for="f in configFields" :key="f.key">
                  <label class="block text-xs text-text-tertiary mb-1.5">{{ f.label }}{{ f.unit ? ` (${f.unit})` : '' }}</label>
                  <input v-model.number="form[f.key]" type="number" :step="f.step ?? 'any'" :placeholder="f.placeholder" class="input-field w-full" />
                </div>
              </div>
            </div>
            <div>
              <label class="block text-xs text-text-tertiary mb-1.5">备注说明</label>
              <textarea v-model="form.description" rows="2" placeholder="可选备注..." class="input-field w-full resize-none"></textarea>
            </div>
          </div>
          <div class="px-6 py-4 border-t border-border-secondary flex items-center justify-end gap-3">
            <button @click="showModal = false" class="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
            <button @click="saveCrudConfig" :disabled="saving"
              class="px-5 py-2 bg-primary hover:bg-primary-hover disabled:opacity-50 text-dark-300 font-semibold rounded-lg text-sm">
              {{ saving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <!-- CRUD 历史 Modal -->
      <div v-if="showCrudHistory" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
        <div class="bg-dark-100 rounded-2xl border border-border-primary w-full max-w-xl max-h-[80vh] overflow-y-auto shadow-2xl">
          <div class="px-6 py-4 border-b border-border-secondary flex items-center justify-between">
            <h3 class="font-bold">配置历史记录</h3>
            <button @click="showCrudHistory = false" class="text-text-tertiary hover:text-text-primary text-xl">✕</button>
          </div>
          <div class="p-4 space-y-2">
            <div v-if="!crudHistoryList.length" class="text-center py-8 text-text-tertiary text-sm">暂无历史记录</div>
            <div v-for="h in crudHistoryList" :key="h.id || h.created_at" class="bg-dark-200 rounded-xl p-3 text-xs space-y-1">
              <div class="flex items-center justify-between">
                <span class="font-semibold">{{ h.config_name || h.name }}</span>
                <span class="text-text-tertiary">{{ fmtTime(h.created_at) }}</span>
              </div>
              <div class="grid grid-cols-2 gap-x-4 text-text-tertiary">
                <div v-for="f in configFields" :key="f.key">
                  {{ f.label }}: <span class="font-mono text-text-secondary">{{ h[f.key] ?? '--' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Toast -->
    <Teleport to="body">
      <div v-if="toast.show" class="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-5 py-3 rounded-xl shadow-xl text-sm font-medium"
        :class="toast.type === 'success' ? 'bg-success text-dark-300' : 'bg-danger text-white'">
        {{ toast.msg }}
      </div>
    </Teleport>

    <!-- 隐藏文件输入 -->
    <input ref="fileInput" type="file" accept=".json" style="display:none" @change="handleFileImport" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import api from '@/services/api.js'
import dayjs from 'dayjs'

// ── 策略类型 ────────────────────────────────────────────────────
const strategyTypes = [
  { type: 'forward_opening',  label: '正套开仓',  icon: '↗' },
  { type: 'reverse_opening',  label: '反套开仓',  icon: '↙' },
  { type: 'forward_closing',  label: '正套平仓',  icon: '↘' },
  { type: 'reverse_closing',  label: '反套平仓',  icon: '↖' },
]

// CRUD 核心字段
const configFields = [
  { key: 'open_threshold',    label: '开仓点差阈值', unit: 'USDT', step: '0.01', placeholder: '2.0' },
  { key: 'close_threshold',   label: '平仓点差阈值', unit: 'USDT', step: '0.01', placeholder: '0.5' },
  { key: 'quantity',          label: '开仓数量',     unit: '',     step: '0.001', placeholder: '0.1' },
  { key: 'max_positions',     label: '最大持仓数',   unit: '',     step: '1',    placeholder: '5'   },
  { key: 'slippage_tolerance',label: '滑点容忍',     unit: 'USDT', step: '0.01', placeholder: '0.5' },
  { key: 'cooldown_seconds',  label: '冷却时间',     unit: 's',    step: '1',    placeholder: '30'  },
  { key: 'stop_loss',         label: '止损阈值',     unit: 'USDT', step: '0.1',  placeholder: ''    },
  { key: 'take_profit',       label: '止盈阈值',     unit: 'USDT', step: '0.1',  placeholder: ''    },
]

// ── 状态 ──────────────────────────────────────────────────────
const activeType      = ref('forward_opening')
const crudOpen        = ref(false)

// 画布
const canvasError     = ref(null)
const successMessage  = ref(null)
const saving          = ref(false)
const isLocked        = ref(false)
const currentTemplate = ref('')
const currentConfigId = ref(null)
const configData      = ref({})
const configHistory   = ref([])
const customTemplates = ref([])
const showHistoryModal      = ref(false)
const showCompareModal      = ref(false)
const showDocModal          = ref(false)
const showSaveTemplateModal = ref(false)
const showTemplateModal     = ref(false)
const compareSource   = ref('')
const compareData     = ref(null)
const newTemplateName = ref('')
const newTemplateDesc = ref('')
const fileInput       = ref(null)

// CRUD
const allConfigs      = ref([])
const effectiveConfig = ref(null)
const loading         = ref(false)
const loadingEffective= ref(false)
const reloading       = ref(false)
const showModal       = ref(false)
const editingConfig   = ref(null)
const showCrudHistory = ref(false)
const crudHistoryList = ref([])
const toast = ref({ show: false, type: 'success', msg: '' })
const defaultForm = () => ({
  config_name: '', config_level: 'strategy_type', strategy_type: activeType.value,
  enabled: true, description: '',
  open_threshold: null, close_threshold: null, quantity: null,
  max_positions: null, slippage_tolerance: null, cooldown_seconds: null,
  stop_loss: null, take_profit: null,
})
const form = ref(defaultForm())

// ── 计算 ──────────────────────────────────────────────────────
const strategyName = computed(() => ({
  forward_opening: '正向开仓', forward_closing: '正向平仓',
  reverse_opening: '反向开仓', reverse_closing: '反向平仓',
}[activeType.value] || activeType.value))

const typeConfigs = computed(() =>
  allConfigs.value.filter(c => !c.strategy_type || c.strategy_type === activeType.value || c.config_level === 'global')
)

// ── 内置模板 ──────────────────────────────────────────────────
const builtinTemplates = {
  conservative: {
    name: '保守型',
    config: { trigger_check_interval:1.0, opening_trigger_count:5, closing_trigger_count:5, binance_timeout:10.0, bybit_timeout:0.5, order_check_interval:0.5, spread_check_interval:5.0, api_spam_prevention_delay:5.0, delayed_single_leg_check_delay:15.0, delayed_single_leg_second_check_delay:2.0, api_retry_times:5, api_retry_delay:1.0, max_binance_limit_retries:50, open_wait_after_cancel_no_trade:5.0, open_wait_after_cancel_part:3.0, close_wait_after_cancel_no_trade:5.0, close_wait_after_cancel_part:3.0, status_polling_interval:10.0, debounce_delay:1.0 }
  },
  balanced: {
    name: '平衡型',
    config: { trigger_check_interval:0.5, opening_trigger_count:3, closing_trigger_count:3, binance_timeout:5.0, bybit_timeout:0.1, order_check_interval:0.2, spread_check_interval:2.0, api_spam_prevention_delay:3.0, delayed_single_leg_check_delay:10.0, delayed_single_leg_second_check_delay:1.0, api_retry_times:3, api_retry_delay:0.5, max_binance_limit_retries:25, open_wait_after_cancel_no_trade:3.0, open_wait_after_cancel_part:2.0, close_wait_after_cancel_no_trade:3.0, close_wait_after_cancel_part:2.0, status_polling_interval:5.0, debounce_delay:0.5 }
  },
  aggressive: {
    name: '激进型',
    config: { trigger_check_interval:0.2, opening_trigger_count:1, closing_trigger_count:1, binance_timeout:2.0, bybit_timeout:0.05, order_check_interval:0.1, spread_check_interval:1.0, api_spam_prevention_delay:1.0, delayed_single_leg_check_delay:5.0, delayed_single_leg_second_check_delay:0.5, api_retry_times:1, api_retry_delay:0.2, max_binance_limit_retries:10, open_wait_after_cancel_no_trade:1.0, open_wait_after_cancel_part:0.5, close_wait_after_cancel_no_trade:1.0, close_wait_after_cancel_part:0.5, status_polling_interval:3.0, debounce_delay:0.2 }
  }
}

// ── 节点构建 ──────────────────────────────────────────────────
function makeElements(strategyType) {
  const triggerParams = []
  if (strategyType === 'reverse_opening' || strategyType === 'forward_opening') {
    triggerParams.push({ key:'opening_trigger_count', label:'开仓触发次数', value:3, unit:'次', step:1, min:1, max:10, recommended:3 })
  } else {
    triggerParams.push({ key:'closing_trigger_count', label:'平仓触发次数', value:3, unit:'次', step:1, min:1, max:10, recommended:3 })
  }

  return [
    { id:'0', type:'custom', position:{x:100,y:-180}, data:{ id:'0', type:'loop', icon:'🔁', label:'手数循环控制', description:'每轮执行单手数，累计达到总手数后结束。remaining = total_qty - current_position', impact:'单手数越小执行越灵活，总手数决定本次任务目标', params:[] } },
    { id:'1', type:'custom', position:{x:100,y:50},   data:{ id:'1', type:'trigger', icon:'🎯', label:'触发控制', description:'每隔检查间隔轮询点差，累计满足触发次数后进入执行', impact:'触发次数越多越稳定，但响应越慢', params:triggerParams } },
    { id:'2', type:'custom', position:{x:100,y:280},  data:{ id:'2', type:'order', icon:'📝', label:'Binance限价单', description:'POST_ONLY挂单，每隔检查间隔轮询成交状态，超时后撤单', impact:'Binance超时 = 检查间隔 × 轮询次数上限',
        params:[
          { key:'binance_timeout', label:'Binance挂单超时', value:5.0, unit:'秒', step:0.5, min:0.1, max:60, recommended:5.0 },
          { key:'order_check_interval', label:'成交状态检查间隔', value:0.2, unit:'秒', step:0.05, min:0.05, max:5, recommended:0.2 },
          { key:'spread_check_interval', label:'点差监控间隔(挂单中)', value:2.0, unit:'秒', step:0.1, min:0.1, max:30, recommended:2.0 }
        ] } },
    { id:'3', type:'custom', position:{x:100,y:530},  data:{ id:'3', type:'bybit', icon:'⚡', label:'Bybit MT5市价单', description:'Binance成交后立即下Bybit市价单，等待MT5成交数据同步', impact:'MT5同步等待时间决定成交量读取准确性',
        params:[
          { key:'bybit_timeout', label:'Bybit下单等待', value:0.1, unit:'秒', step:0.01, min:0.01, max:10, recommended:0.1 },
          { key:'mt5_deal_sync_wait', label:'MT5成交同步等待', value:3.0, unit:'秒', step:0.5, min:0.5, max:30, recommended:3.0 }
        ] } },
    { id:'4', type:'custom', position:{x:500,y:530},  data:{ id:'4', type:'retry', icon:'🔄', label:'Bybit成交验证/重试', description:'读取MT5 deals验证实际成交量，不足95%则重试补单', impact:'重试次数越多越能保证双边成交，但耗时更长',
        params:[
          { key:'api_retry_times', label:'Bybit补单重试次数', value:1, unit:'次', step:1, min:0, max:5, recommended:1 },
          { key:'api_retry_delay', label:'重试间隔', value:0.5, unit:'秒', step:0.1, min:0.1, max:10, recommended:0.5 },
          { key:'max_binance_limit_retries', label:'Binance限价单最大轮询次数', value:25, unit:'次', step:1, min:5, max:100, recommended:25 }
        ] } },
    { id:'5', type:'custom', position:{x:500,y:280},  data:{ id:'5', type:'check', icon:'🔍', label:'单腿检测(异步)', description:'非阻塞异步任务：等待后对比仓位快照，Bybit/Binance < 60%则报警', impact:'延迟时间越长检测越准确，但报警越滞后',
        params:[
          { key:'delayed_single_leg_check_delay', label:'第一次检测延迟', value:10.0, unit:'秒', step:1, min:1, max:60, recommended:10.0 },
          { key:'delayed_single_leg_second_check_delay', label:'第二次检测延迟', value:1.0, unit:'秒', step:0.1, min:0.1, max:10, recommended:1.0 }
        ] } },
    { id:'6', type:'custom', position:{x:100,y:780},  data:{ id:'6', type:'complete', icon:'✅', label:'手数累计 & 完成判断', description:'record_opening累加Binance成交量(主腿)，current_position >= total_qty则结束循环', impact:'每轮成交量以Binance主腿成交量计入',
        params:[
          { key:'api_spam_prevention_delay', label:'执行后防频繁延迟', value:3.0, unit:'秒', step:0.5, min:0.5, max:30, recommended:3.0 }
        ] } },
    { id:'7', type:'custom', position:{x:500,y:780},  data:{ id:'7', type:'cancel', icon:'❌', label:'撤单后等待', description:'Binance超时撤单后等待，区分未成交和部分成交两种情况', impact:'等待时间影响重新挂单的速度',
        params:[
          { key:'open_wait_after_cancel_no_trade', label:'开仓撤单-未成交等待', value:3.0, unit:'秒', step:0.5, min:0.5, max:30, recommended:3.0 },
          { key:'open_wait_after_cancel_part', label:'开仓撤单-部分成交等待', value:2.0, unit:'秒', step:0.5, min:0.5, max:30, recommended:2.0 },
          { key:'close_wait_after_cancel_no_trade', label:'平仓撤单-未成交等待', value:3.0, unit:'秒', step:0.5, min:0.5, max:30, recommended:3.0 },
          { key:'close_wait_after_cancel_part', label:'平仓撤单-部分成交等待', value:2.0, unit:'秒', step:0.5, min:0.5, max:30, recommended:2.0 }
        ] } },
    { id:'8', type:'custom', position:{x:900,y:280},  data:{ id:'8', type:'frontend', icon:'🖥️', label:'前端交互', description:'前端轮询状态和防抖配置', impact:'轮询频率影响界面更新速度',
        params:[
          { key:'status_polling_interval', label:'状态轮询间隔', value:5.0, unit:'秒', step:1, min:1, max:30, recommended:5.0 },
          { key:'debounce_delay', label:'防抖延迟', value:0.5, unit:'秒', step:0.1, min:0.1, max:2, recommended:0.5 }
        ] } },
    // 边
    { id:'e0-1', source:'0', target:'1', type:'smoothstep', animated:true, label:'开始每轮' },
    { id:'e1-2', source:'1', target:'2', type:'smoothstep', animated:true, label:'触发成功→挂Binance限价单' },
    { id:'e2-3', source:'2', target:'3', type:'smoothstep', animated:true, label:'Binance成交→下Bybit市价单' },
    { id:'e3-4', source:'3', target:'4', type:'smoothstep', animated:true, label:'验证MT5成交量' },
    { id:'e4-6', source:'4', target:'6', type:'smoothstep', animated:true, label:'成交≥95%→累计手数' },
    { id:'e6-0', source:'6', target:'0', type:'smoothstep', animated:true, style:{stroke:'#4ade80'}, label:'未达总手数→下一轮' },
    { id:'e3-5', source:'3', target:'5', type:'smoothstep', style:{stroke:'#a78bfa',strokeDasharray:'5,5'}, label:'异步检测单腿' },
    { id:'e2-7', source:'2', target:'7', type:'smoothstep', style:{stroke:'#f97316'}, label:'Binance超时撤单' },
    { id:'e7-1', source:'7', target:'1', type:'smoothstep', style:{stroke:'#f97316'}, label:'等待后重新触发' },
    { id:'e4-3', source:'4', target:'3', type:'smoothstep', style:{stroke:'#fb923c',strokeDasharray:'5,5'}, label:'成交不足→补单重试' },
    { id:'e2-1', source:'2', target:'1', type:'smoothstep', style:{stroke:'#94a3b8',strokeDasharray:'5,5'}, label:'Binance未成交→重置触发' },
  ]
}

const elements = ref(makeElements('forward_opening'))

// ── 切换策略 ──────────────────────────────────────────────────
async function switchStrategy(type) {
  activeType.value = type
  elements.value = makeElements(type)
  configData.value = {}
  isLocked.value = false
  currentTemplate.value = ''
  currentConfigId.value = null
  await Promise.all([loadWorkflowConfig(), fetchEffective(), fetchTemplatesForType()])
}

// ── 加载画布配置 ─────────────────────────────────────────────
async function loadWorkflowConfig() {
  try {
    const r = await api.get(`/api/v1/timing-configs/effective/${activeType.value}`)
    const config = r.data
    configData.value = config

    // 填充 nodes
    elements.value.forEach(el => {
      if (el.data?.params) {
        el.data.params.forEach(p => {
          if (config[p.key] !== undefined) p.value = config[p.key]
        })
      }
    })

    // 查配置锁定状态
    const r2 = await api.get('/api/v1/timing-configs')
    const configs = Array.isArray(r2.data) ? r2.data : r2.data?.configs ?? []
    const found = configs.find(c => c.config_level === 'strategy_type' && c.strategy_type === activeType.value)
    if (found) {
      currentConfigId.value = found.id
      isLocked.value = found.is_locked || false
      currentTemplate.value = found.template || ''
    }
  } catch (err) {
    console.error('加载画布配置失败', err)
  }
}

async function loadWorkflowHistory() {
  try {
    const r = await api.get(`/api/v1/timing-configs/history/${activeType.value}`)
    configHistory.value = Array.isArray(r.data) ? r.data : []
  } catch { configHistory.value = [] }
}

async function loadCustomTemplates() {
  try {
    const r = await api.get(`/api/v1/timing-configs/templates/${activeType.value}`)
    customTemplates.value = Array.isArray(r.data) ? r.data : []
  } catch { customTemplates.value = [] }
}

// ── 参数验证 ──────────────────────────────────────────────────
function findParam(key) {
  for (const el of elements.value) {
    if (el.data?.params) {
      const p = el.data.params.find(p => p.key === key)
      if (p) return p
    }
  }
  return null
}

function validateParam(param) {
  param.warning = null
  param.error = null
  if (param.value < param.min || param.value > param.max) {
    param.error = `值必须在 ${param.min}-${param.max} 之间`
    return
  }
  const deviation = Math.abs(param.value - param.recommended) / param.recommended
  if (deviation > 0.5) param.warning = '偏离推荐值较大，可能影响性能'

  const key = param.key
  if (key === 'binance_timeout') {
    const oci = findParam('order_check_interval')
    if (oci && param.value < oci.value) { param.error = 'Binance超时不能小于订单检查间隔'; return }
    if (param.value < 3.0) param.warning = '超时时间过短，可能导致订单未完成就超时'
  }
  if (key === 'order_check_interval') {
    if (param.value < 0.1) { param.error = '订单检查间隔过小会导致API频繁调用'; return }
    const bt = findParam('binance_timeout')
    if (bt && param.value > bt.value) param.error = '订单检查间隔不能大于Binance超时时间'
  }
  if (key === 'api_spam_prevention_delay') {
    if (param.value < 1.0) param.warning = '延迟过短可能导致API被限流'
    if (param.value > 10.0) param.warning = '延迟过长会影响执行速度'
  }
  if (key === 'mt5_deal_sync_wait') {
    if (param.value < 1.0) param.warning = '等待时间过短，MT5可能还未同步成交数据'
    if (param.value > 10.0) param.warning = '等待时间过长会影响执行效率'
  }
  if (key === 'delayed_single_leg_check_delay') {
    const sc = findParam('delayed_single_leg_second_check_delay')
    if (sc && param.value < sc.value) param.error = '第一次检查延迟应该大于第二次检查延迟'
  }
  if (key === 'api_retry_delay') {
    const rt = findParam('api_retry_times')
    if (rt && param.value * rt.value > 10) param.warning = `总重试时间 (${(param.value * rt.value).toFixed(1)}秒) 过长`
  }
  if (key.includes('wait_after_cancel')) {
    if (param.value < 1.0) param.warning = '等待时间过短可能导致订单状态未更新'
    if (param.value > 10.0) param.warning = '等待时间过长会影响重新下单速度'
  }
}

function onParamChange(nodeId, paramKey, value) {
  configData.value[paramKey] = value
  currentTemplate.value = ''
}

// ── 保存画布配置 ──────────────────────────────────────────────
async function saveWorkflowConfig() {
  saving.value = true
  canvasError.value = null
  successMessage.value = null
  try {
    let hasError = false
    elements.value.forEach(el => {
      el.data?.params?.forEach(p => { validateParam(p); if (p.error) hasError = true })
    })
    if (hasError) { canvasError.value = '配置验证失败，请检查标红的参数'; return }

    const updateData = { template: currentTemplate.value }
    elements.value.forEach(el => {
      el.data?.params?.forEach(p => { updateData[p.key] = p.value })
    })

    const r2 = await api.get('/api/v1/timing-configs')
    const configs = Array.isArray(r2.data) ? r2.data : r2.data?.configs ?? []
    const existing = configs.find(c => c.config_level === 'strategy_type' && c.strategy_type === activeType.value)
    if (existing) {
      await api.put(`/api/v1/timing-configs/${existing.id}`, updateData)
    } else {
      await api.post('/api/v1/timing-configs', { config_level:'strategy_type', strategy_type:activeType.value, ...updateData })
    }
    await loadWorkflowHistory()
    showFlash('配置保存成功！')
  } catch (err) {
    canvasError.value = '保存失败: ' + (err.response?.data?.detail || err.message)
  } finally {
    saving.value = false
  }
}

function showFlash(msg) {
  successMessage.value = msg
  setTimeout(() => { successMessage.value = null }, 3000)
}

// ── 重置画布 ──────────────────────────────────────────────────
function resetConfig() {
  if (!confirm('确定要重置为默认值吗？')) return
  const tpl = builtinTemplates.balanced
  elements.value.forEach(el => {
    el.data?.params?.forEach(p => {
      if (tpl.config[p.key] !== undefined) {
        p.value = tpl.config[p.key]
        p.warning = null; p.error = null
        configData.value[p.key] = p.value
      }
    })
  })
  currentTemplate.value = 'balanced'
  showFlash('已重置为平衡型默认值')
}

// ── 锁定 ──────────────────────────────────────────────────────
async function toggleLock() {
  if (!currentConfigId.value) { canvasError.value = '配置不存在，无法锁定'; return }
  const newState = !isLocked.value
  if (!confirm(newState ? '确定要锁定此配置吗？' : '确定要解锁此配置吗？')) return
  try {
    await api.put(`/api/v1/timing-configs/${currentConfigId.value}`, { is_locked: newState })
    isLocked.value = newState
    showFlash(newState ? '配置已锁定' : '配置已解锁')
  } catch (err) { canvasError.value = '切换锁定失败: ' + (err.response?.data?.detail || err.message) }
}

// ── 内置模板 ──────────────────────────────────────────────────
function applyTemplateByKey(key) {
  const tpl = builtinTemplates[key]
  if (!tpl) return
  if (!confirm(`确定要应用${tpl.name}配置吗？这将覆盖当前所有参数。`)) return
  elements.value.forEach(el => {
    el.data?.params?.forEach(p => {
      if (tpl.config[p.key] !== undefined) {
        p.value = tpl.config[p.key]
        configData.value[p.key] = p.value
        validateParam(p)
      }
    })
  })
  currentTemplate.value = key
  showFlash(`已应用${tpl.name}配置模板`)
}

// ── 历史 ──────────────────────────────────────────────────────
async function openHistoryModal() {
  await loadWorkflowHistory()
  showHistoryModal.value = true
}

function restoreHistory(h) {
  if (!confirm(`确定要恢复到 ${formatTime(h.created_at)} 的配置吗？`)) return
  const cfg = h.config_data || h.config || {}
  elements.value.forEach(el => {
    el.data?.params?.forEach(p => {
      if (cfg[p.key] !== undefined) { p.value = cfg[p.key]; configData.value[p.key] = p.value; validateParam(p) }
    })
  })
  currentTemplate.value = h.template || ''
  showHistoryModal.value = false
  showFlash('已恢复历史配置')
}

function compareWithHistory(h) {
  const cfg = h.config_data || h.config || {}
  compareSource.value = 'history_' + h.id
  generateCompareData(cfg)
  showHistoryModal.value = false
  showCompareModal.value = true
}

// ── 对比 ──────────────────────────────────────────────────────
function generateCompareData(compareCfg) {
  if (!compareCfg) {
    if (compareSource.value.startsWith('custom_')) {
      const id = parseInt(compareSource.value.replace('custom_', ''))
      const t = customTemplates.value.find(t => t.id === id)
      if (t) compareCfg = t.config_data
    } else if (builtinTemplates[compareSource.value]) {
      compareCfg = builtinTemplates[compareSource.value].config
    } else return
  }
  const labels = {}
  elements.value.forEach(el => { el.data?.params?.forEach(p => { labels[p.key] = { label: p.label, unit: p.unit } }) })
  compareData.value = Object.keys(compareCfg).filter(k => labels[k]).map(k => {
    const current = configData.value[k]
    const compare = compareCfg[k]
    const isDifferent = current !== compare
    return { key: k, label: labels[k].label, unit: labels[k].unit, current, compare, diff: isDifferent ? (current - compare) : 0, isDifferent }
  })
}

// ── 自定义模板 ────────────────────────────────────────────────
async function openTemplateModal() {
  await loadCustomTemplates()
  showTemplateModal.value = true
}

async function saveAsTemplate() {
  if (!newTemplateName.value.trim()) return
  try {
    const cfg = {}
    elements.value.forEach(el => { el.data?.params?.forEach(p => { cfg[p.key] = p.value }) })
    await api.post('/api/v1/timing-configs/templates', {
      strategy_type: activeType.value,
      name: newTemplateName.value.trim(),
      description: newTemplateDesc.value.trim() || null,
      config_data: cfg
    })
    await loadCustomTemplates()
    showSaveTemplateModal.value = false
    newTemplateName.value = ''; newTemplateDesc.value = ''
    showFlash('模板保存成功')
  } catch (err) { canvasError.value = '保存模板失败: ' + (err.response?.data?.detail || err.message) }
}

function applyCustomTemplate(tpl) {
  if (!confirm(`确定要应用模板"${tpl.name}"吗？这将覆盖当前所有参数。`)) return
  elements.value.forEach(el => {
    el.data?.params?.forEach(p => {
      if (tpl.config_data[p.key] !== undefined) { p.value = tpl.config_data[p.key]; configData.value[p.key] = p.value; validateParam(p) }
    })
  })
  currentTemplate.value = 'custom_' + tpl.id
  showTemplateModal.value = false
  showFlash(`已应用模板"${tpl.name}"`)
}

function compareWithTemplate(tpl) {
  compareSource.value = 'custom_' + tpl.id
  showTemplateModal.value = false
  showCompareModal.value = true
}

async function deleteCustomTemplate(id) {
  const tpl = customTemplates.value.find(t => t.id === id)
  if (!tpl || !confirm(`确定要删除模板"${tpl.name}"吗？`)) return
  try {
    await api.delete(`/api/v1/timing-configs/templates/${id}`)
    await loadCustomTemplates()
    showFlash('模板已删除')
  } catch (err) { canvasError.value = '删除模板失败: ' + (err.response?.data?.detail || err.message) }
}

// ── 导出/导入 ─────────────────────────────────────────────────
function exportConfig() {
  const cfg = {}
  elements.value.forEach(el => { el.data?.params?.forEach(p => { cfg[p.key] = p.value }) })
  const blob = new Blob([JSON.stringify({ strategy_type: activeType.value, template: currentTemplate.value, timestamp: new Date().toISOString(), config: cfg }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `timing_config_${activeType.value}_${Date.now()}.json`
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
  URL.revokeObjectURL(url)
  showFlash('配置已导出')
}

function importConfig() { fileInput.value.click() }

function handleFileImport(event) {
  const file = event.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = e => {
    try {
      const data = JSON.parse(e.target.result)
      if (!data.config) throw new Error('无效的配置文件格式')
      if (!confirm(`确定要导入配置吗？\n来源: ${data.strategy_type || '未知'}\n时间: ${data.timestamp || '未知'}`)) return
      elements.value.forEach(el => {
        el.data?.params?.forEach(p => {
          if (data.config[p.key] !== undefined) { p.value = data.config[p.key]; configData.value[p.key] = p.value; validateParam(p) }
        })
      })
      currentTemplate.value = data.template || ''
      showFlash('配置已导入')
    } catch (err) { canvasError.value = '导入失败: ' + err.message }
  }
  reader.readAsText(file)
  event.target.value = ''
}

// ── CRUD ──────────────────────────────────────────────────────
async function fetchAllConfigs() {
  loading.value = true
  try {
    const r = await api.get('/api/v1/timing-configs')
    allConfigs.value = Array.isArray(r.data) ? r.data : r.data?.configs ?? []
  } catch { allConfigs.value = [] }
  finally { loading.value = false }
}

async function fetchEffective() {
  loadingEffective.value = true
  effectiveConfig.value = null
  try {
    const r = await api.get(`/api/v1/timing-configs/effective/${activeType.value}`)
    effectiveConfig.value = r.data
  } catch { effectiveConfig.value = null }
  finally { loadingEffective.value = false }
}

async function fetchTemplatesForType() {
  // loaded via loadCustomTemplates when needed
}

async function reloadConfigs() {
  reloading.value = true
  try {
    await api.post('/api/v1/timing-configs/reload')
    await fetchAllConfigs(); await fetchEffective()
    showToast('success', '配置已重新加载')
  } catch (e) { showToast('error', '重载失败：' + (e.response?.data?.detail ?? e.message)) }
  finally { reloading.value = false }
}

function openCreateModal() {
  editingConfig.value = null; form.value = defaultForm(); form.value.strategy_type = activeType.value; showModal.value = true
}
function openEditModal(cfg) {
  editingConfig.value = cfg; form.value = { ...defaultForm(), ...cfg }; showModal.value = true
}

async function saveCrudConfig() {
  if (!form.value.config_name.trim()) { showToast('error', '配置名称不能为空'); return }
  saving.value = true
  try {
    if (editingConfig.value) {
      await api.put(`/api/v1/timing-configs/${editingConfig.value.id}`, form.value)
      showToast('success', '配置已更新')
    } else {
      await api.post('/api/v1/timing-configs', form.value)
      showToast('success', '配置已创建')
    }
    showModal.value = false
    await fetchAllConfigs(); await fetchEffective()
  } catch (e) { showToast('error', '保存失败：' + (e.response?.data?.detail ?? e.message)) }
  finally { saving.value = false }
}

async function deleteConfig(cfg) {
  if (!confirm(`确认删除配置「${cfg.config_name || cfg.name}」？`)) return
  try {
    await api.delete(`/api/v1/timing-configs/${cfg.id}`)
    showToast('success', '已删除')
    await fetchAllConfigs(); await fetchEffective()
  } catch (e) { showToast('error', '删除失败') }
}

async function openCrudHistoryModal(cfg) {
  crudHistoryList.value = []; showCrudHistory.value = true
  try {
    const r = await api.get(`/api/v1/timing-configs/history/${activeType.value}`)
    crudHistoryList.value = Array.isArray(r.data) ? r.data : []
  } catch { crudHistoryList.value = [] }
}

// ── 工具 ──────────────────────────────────────────────────────
function showToast(type, msg) {
  toast.value = { show: true, type, msg }
  setTimeout(() => toast.value.show = false, 3000)
}
function formatTime(ts) { return ts ? new Date(ts).toLocaleString('zh-CN') : '' }
function fmtTime(v) { return v ? dayjs(v).format('MM-DD HH:mm:ss') : '--' }

// ── 监听 ──────────────────────────────────────────────────────
watch(activeType, () => { fetchAllConfigs(); fetchEffective() })
watch(compareSource, () => { if (compareSource.value && !compareSource.value.startsWith('history_')) generateCompareData(null) })

onMounted(async () => {
  await Promise.all([fetchAllConfigs(), fetchEffective(), loadWorkflowConfig(), loadWorkflowHistory(), loadCustomTemplates()])
})
</script>

<style scoped>
.strategies-page {
  display: flex;
  flex-direction: column;
  gap: 0;
  min-height: 100vh;
  background: #1a1d23;
}

/* 策略类型选择 */
.type-selector {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  background: #252930;
  border-bottom: 1px solid #2d3139;
}
.type-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #2d3139;
  border: 1px solid #3d4451;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: #b0b8c4;
  font-size: 14px;
}
.type-card:hover { border-color: #4CAF50; color: #e0e0e0; }
.type-card.active { background: #4CAF50; border-color: #4CAF50; color: white; font-weight: 600; }
.type-icon { font-size: 18px; }

/* 画布 */
.workflow-canvas {
  display: flex;
  flex-direction: column;
  height: 900px;
  background: #1a1d23;
  border-bottom: 1px solid #2d3139;
}
.canvas-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: #252930;
  border-bottom: 1px solid #2d3139;
  flex-wrap: wrap;
  gap: 10px;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.canvas-header h2 { margin: 0; font-size: 15px; color: #e0e0e0; }
.lock-badge { padding: 3px 10px; background: #ff9800; color: white; border-radius: 4px; font-size: 12px; }
.header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.template-group { display: flex; gap: 6px; padding: 3px; background: #1a1d23; border-radius: 6px; }
.btn-template { padding: 6px 14px; background: #2d3139; border: 1px solid #3d4451; border-radius: 4px; color: #e0e0e0; font-size: 13px; cursor: pointer; transition: all 0.2s; }
.btn-template:hover { background: #3d4451; border-color: #4CAF50; }
.btn-template.active { background: #4CAF50; border-color: #4CAF50; color: white; font-weight: 500; }
.btn-template:disabled { opacity: 0.5; cursor: not-allowed; }
.action-buttons { display: flex; gap: 6px; flex-wrap: wrap; }
.btn-secondary { padding: 6px 12px; background: #2d3139; border: 1px solid #3d4451; border-radius: 4px; color: #e0e0e0; font-size: 12px; cursor: pointer; transition: all 0.2s; }
.btn-secondary:hover { background: #3d4451; }
.btn-secondary:disabled { opacity:0.5; cursor: not-allowed; }
.btn-primary { padding: 6px 14px; background: #4CAF50; border: none; border-radius: 4px; color: white; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
.btn-primary:hover { background: #43a047; }
.btn-primary:disabled { opacity:0.5; cursor: not-allowed; }
.workflow-flow { flex: 1; background: #1a1d23; }

/* 节点 */
:deep(.custom-node) {
  background: #252930;
  border: 1px solid #3d4451;
  border-radius: 8px;
  min-width: 220px;
  max-width: 280px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
:deep(.custom-node.loop)     { border-color: #4CAF50; }
:deep(.custom-node.trigger)  { border-color: #2196F3; }
:deep(.custom-node.order)    { border-color: #FF9800; }
:deep(.custom-node.bybit)    { border-color: #9C27B0; }
:deep(.custom-node.retry)    { border-color: #F44336; }
:deep(.custom-node.check)    { border-color: #a78bfa; }
:deep(.custom-node.complete) { border-color: #4ade80; }
:deep(.custom-node.cancel)   { border-color: #F97316; }
:deep(.custom-node.frontend) { border-color: #64748b; }
:deep(.node-header) { display:flex; align-items:center; gap:8px; padding:10px 12px; border-bottom:1px solid #2d3139; background:#2d3139; border-radius:8px 8px 0 0; }
:deep(.node-icon) { font-size:16px; }
:deep(.node-title) { font-size:13px; font-weight:600; color:#e0e0e0; }
:deep(.node-content) { padding:10px 12px; }
:deep(.param-row) { margin-bottom:8px; }
:deep(.param-row label) { display:block; font-size:11px; color:#8899aa; margin-bottom:3px; }
:deep(.param-input) { display:flex; align-items:center; gap:4px; }
:deep(.param-input input) { flex:1; padding:4px 8px; background:#1a1d23; border:1px solid #3d4451; border-radius:4px; color:#e0e0e0; font-size:12px; font-family:monospace; }
:deep(.param-input input:focus) { outline:none; border-color:#4CAF50; }
:deep(.param-input input.warning) { border-color:#FF9800; }
:deep(.param-input input.error) { border-color:#F44336; }
:deep(.param-unit) { font-size:11px; color:#8899aa; white-space:nowrap; }
:deep(.param-hint) { display:block; font-size:10px; color:#6b7280; margin-top:2px; }
:deep(.text-warning) { color:#FF9800 !important; }
:deep(.text-error) { color:#F44336 !important; }
:deep(.node-description) { padding:6px 12px; font-size:11px; color:#8899aa; border-top:1px solid #2d3139; }
:deep(.node-impact) { padding:4px 12px 8px; font-size:11px; color:#4CAF50; }

.error-message { padding: 8px 16px; background: #2d1b1b; color: #ff6b6b; font-size: 13px; border-top: 1px solid #4a2020; }
.success-message { padding: 8px 16px; background: #1b2d1b; color: #6bff6b; font-size: 13px; border-top: 1px solid #204a20; }

/* CRUD */
.crud-section { background: #252930; border-top: 1px solid #2d3139; }
.crud-header { display:flex; align-items:center; justify-content:space-between; padding: 12px 20px; cursor:pointer; user-select:none; }
.crud-header:hover { background: #2d3139; }
.effective-bar { margin: 0 20px 8px; padding: 12px; background: linear-gradient(to right, rgba(76,175,80,0.1), transparent); border: 1px solid rgba(76,175,80,0.3); border-radius: 12px; }
.crud-toolbar { display:flex; gap:8px; padding:8px 20px; border-bottom:1px solid #2d3139; }
.btn-sm-outline { padding:5px 12px; background:#1a1d23; border:1px solid #3d4451; border-radius:6px; color:#b0b8c4; font-size:12px; cursor:pointer; transition:all 0.2s; }
.btn-sm-outline:hover { border-color:#4CAF50; color:#e0e0e0; }
.btn-sm-outline:disabled { opacity:0.5; cursor:not-allowed; }
.btn-sm-primary { padding:5px 12px; background:#4CAF50; border:none; border-radius:6px; color:white; font-size:12px; font-weight:600; cursor:pointer; }
.config-list { padding: 0 20px 12px; }
.config-row { display:flex; align-items:start; gap:12px; padding:12px 0; border-bottom:1px solid #2d3139; }
.config-row:last-child { border-bottom:none; }
.badge-level { font-size:11px; padding:1px 6px; background:#2d3139; border-radius:4px; color:#8899aa; }
.badge-active { font-size:11px; padding:1px 6px; background:rgba(76,175,80,0.2); border-radius:4px; color:#4CAF50; }
.badge-disabled { font-size:11px; padding:1px 6px; background:#2d3139; border-radius:4px; color:#6b7280; }
.btn-xs { padding:4px 10px; font-size:11px; background:#2d3139; border:1px solid #3d4451; border-radius:6px; color:#b0b8c4; cursor:pointer; transition:all 0.2s; }
.btn-xs:hover { border-color:#4CAF50; color:#e0e0e0; }
.btn-xs.danger { color:#ef4444; border-color:rgba(239,68,68,0.3); }
.btn-xs.danger:hover { background:rgba(239,68,68,0.1); }
.input-field { @apply px-3 py-2 bg-dark-200 border border-border-primary rounded-lg text-sm focus:outline-none focus:border-primary text-text-primary transition-colors; }

/* Modals */
.modal-overlay { position:fixed; inset:0; z-index:50; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.7); padding:16px; }
.modal-content { background:#252930; border:1px solid #3d4451; border-radius:12px; width:100%; max-width:560px; max-height:80vh; overflow-y:auto; box-shadow:0 20px 60px rgba(0,0,0,0.5); }
.modal-large { max-width:760px; }
.modal-header { display:flex; align-items:center; justify-content:space-between; padding:16px 20px; border-bottom:1px solid #2d3139; }
.modal-header h3 { margin:0; font-size:15px; color:#e0e0e0; }
.btn-close { background:none; border:none; color:#8899aa; font-size:16px; cursor:pointer; padding:4px; }
.btn-close:hover { color:#e0e0e0; }
.modal-body { padding:20px; }
.empty-state { text-align:center; color:#6b7280; padding:32px; font-size:13px; }
.history-list { display:flex; flex-direction:column; gap:8px; }
.history-item { display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:#2d3139; border-radius:8px; }
.history-info { display:flex; gap:12px; font-size:12px; }
.history-time { color:#b0b8c4; }
.history-user { color:#8899aa; }
.history-template { color:#4CAF50; }
.history-actions { display:flex; gap:6px; }
.compare-controls { margin-bottom:12px; }
.form-select { width:100%; padding:8px 12px; background:#1a1d23; border:1px solid #3d4451; border-radius:6px; color:#e0e0e0; font-size:13px; }
.compare-table { overflow-x:auto; }
.compare-table table { width:100%; border-collapse:collapse; font-size:13px; }
.compare-table th { padding:8px 12px; text-align:left; background:#2d3139; color:#8899aa; font-weight:500; }
.compare-table td { padding:8px 12px; border-top:1px solid #2d3139; color:#e0e0e0; }
.compare-table tr.diff td { background:rgba(255,152,0,0.05); }
.diff-badge { padding:2px 6px; background:rgba(255,152,0,0.2); color:#FF9800; border-radius:4px; font-size:11px; }
.same-badge { color:#6b7280; font-size:11px; }
.doc-content { font-size:13px; color:#b0b8c4; }
.doc-section { margin-bottom:20px; }
.doc-section h4 { color:#e0e0e0; font-size:14px; margin:0 0 10px; }
.doc-item { margin-bottom:12px; padding-left:12px; border-left:2px solid #3d4451; }
.doc-item strong { color:#e0e0e0; display:block; margin-bottom:4px; }
.doc-item p { margin:4px 0; }
.doc-impact { color:#4CAF50 !important; }
.form-group { margin-bottom:14px; }
.form-group label { display:block; font-size:12px; color:#8899aa; margin-bottom:6px; }
.form-input { width:100%; padding:8px 12px; background:#1a1d23; border:1px solid #3d4451; border-radius:6px; color:#e0e0e0; font-size:13px; }
.form-textarea { width:100%; padding:8px 12px; background:#1a1d23; border:1px solid #3d4451; border-radius:6px; color:#e0e0e0; font-size:13px; resize:vertical; }
.modal-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
.template-list { display:flex; flex-direction:column; gap:8px; }
.template-item { display:flex; align-items:center; justify-content:space-between; padding:12px 14px; background:#2d3139; border-radius:8px; }
.template-info h4 { margin:0 0 4px; font-size:13px; color:#e0e0e0; }
.template-desc { font-size:12px; color:#8899aa; margin:0 0 4px; }
.template-time { font-size:11px; color:#6b7280; }
.template-actions { display:flex; gap:6px; }
.btn-sm { padding:5px 12px; background:#2d3139; border:1px solid #3d4451; border-radius:6px; color:#b0b8c4; font-size:12px; cursor:pointer; }
.btn-sm.btn-primary { background:#4CAF50; border-color:#4CAF50; color:white; }
.btn-sm.btn-danger { color:#ef4444; border-color:rgba(239,68,68,0.3); }
.btn-sm.btn-danger:hover { background:rgba(239,68,68,0.1); }
</style>
