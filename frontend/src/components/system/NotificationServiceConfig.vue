<template>
  <div class="space-y-6">
    <!-- 飞书配置 -->
    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-xl font-bold">飞书机器人配置</h2>
        <label class="flex items-center cursor-pointer">
          <input
            type="checkbox"
            v-model="feishuConfig.is_enabled"
            class="sr-only peer"
          />
          <div class="relative w-11 h-6 bg-dark-300 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
          <span class="ml-3 text-sm font-medium">{{ feishuConfig.is_enabled ? '已启用' : '已禁用' }}</span>
        </label>
      </div>

      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium mb-2">App ID</label>
          <input
            v-model="feishuConfig.app_id"
            type="text"
            placeholder="cli_a9235819f078dcbd"
            :disabled="!feishuConfig.is_enabled"
            class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <div class="text-xs text-text-secondary mt-1">飞书开放平台应用凭证</div>
        </div>

        <div>
          <label class="block text-sm font-medium mb-2">App Secret</label>
          <div class="relative">
            <input
              v-model="feishuConfig.app_secret"
              :type="showSecret ? 'text' : 'password'"
              placeholder="请输入App Secret"
              :disabled="!feishuConfig.is_enabled"
              class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed pr-10"
            />
            <button
              @click="showSecret = !showSecret"
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary"
            >
              <svg v-if="!showSecret" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
              </svg>
            </button>
          </div>
          <div class="text-xs text-text-secondary mt-1">请妥善保管，不要泄露</div>
        </div>

        <div>
          <label class="block text-sm font-medium mb-2">测试接收人</label>
          <div class="flex gap-2">
            <select
              v-model="selectedUserId"
              @change="onUserSelect"
              class="flex-1 px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
            >
              <option value="">-- 选择用户 --</option>
              <option v-for="user in usersWithFeishu" :key="user.user_id" :value="user.user_id">
                {{ user.username }}
                <template v-if="user.feishu_open_id">(Open ID)</template>
                <template v-else-if="user.feishu_mobile">(手机号)</template>
                <template v-else-if="user.email">(邮箱)</template>
              </option>
            </select>
            <button
              @click="refreshUsers"
              class="px-3 py-2 bg-dark-300 border border-border-primary rounded hover:bg-dark-200 transition-colors"
              title="刷新用户列表"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          </div>
          <input
            v-model="testRecipient"
            type="text"
            placeholder="或手动输入飞书open_id/手机号/邮箱"
            class="w-full px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary mt-2"
          />
          <div class="text-xs text-text-secondary mt-1">
            <span v-if="selectedUserInfo" class="text-primary">
              已选择: {{ selectedUserInfo }}
            </span>
            <span v-else>
              从列表选择用户或手动输入接收人ID
            </span>
          </div>
        </div>

        <div class="flex space-x-3">
          <button
            @click="saveConfig('feishu')"
            :disabled="saving"
            class="btn-primary"
          >
            <svg v-if="!saving" class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
            <svg v-else class="animate-spin w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {{ saving ? '保存中...' : '保存配置' }}
          </button>
          <button
            @click="testNotification('feishu')"
            :disabled="testing || !feishuConfig.is_enabled || !testRecipient"
            class="btn-secondary"
          >
            <svg v-if="!testing" class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
            <svg v-else class="animate-spin w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {{ testing ? '发送中...' : '发送测试消息' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 通知模板 -->
    <div class="card">
      <div class="mb-4">
        <h2 class="text-xl font-bold mb-2">通知模板管理</h2>
        <p class="text-sm text-text-secondary">
          系统级配置：所有模板设置（包括声音提醒）对全系统所有用户生效
        </p>
      </div>

      <div class="flex space-x-2 mb-4">
        <button
          v-for="cat in categories"
          :key="cat.value"
          @click="templateCategory = cat.value; loadTemplates()"
          :class="['px-4 py-2 rounded transition-colors', templateCategory === cat.value ? 'bg-primary text-white' : 'bg-dark-300 text-text-secondary hover:bg-dark-200']"
        >
          {{ cat.label }}
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-border-primary">
              <th class="text-left py-3 px-4">模板名称</th>
              <th class="text-left py-3 px-4">分类</th>
              <th class="text-left py-3 px-4">通知渠道</th>
              <th class="text-left py-3 px-4">优先级</th>
              <th class="text-left py-3 px-4">标题模板</th>
              <th class="text-left py-3 px-4">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="template in templates"
              :key="template.template_id"
              class="border-b border-border-secondary hover:bg-dark-50"
            >
              <td class="py-3 px-4">{{ template.template_name }}</td>
              <td class="py-3 px-4">
                <span
                  :class="['px-2 py-1 rounded text-xs', getCategoryClass(template.category)]"
                >
                  {{ getCategoryLabel(template.category) }}
                </span>
              </td>
              <td class="py-3 px-4">
                <div class="flex gap-1">
                  <span v-if="template.enable_feishu" class="px-2 py-1 bg-success/20 text-success rounded text-xs">飞书</span>
                  <span v-if="template.enable_email" class="px-2 py-1 bg-blue-500/20 text-blue-400 rounded text-xs">邮件</span>
                  <span v-if="template.enable_sms" class="px-2 py-1 bg-warning/20 text-warning rounded text-xs">短信</span>
                </div>
              </td>
              <td class="py-3 px-4">
                <span
                  :class="['px-2 py-1 rounded text-xs', getPriorityClass(template.priority)]"
                >
                  {{ getPriorityLabel(template.priority) }}
                </span>
              </td>
              <td class="py-3 px-4 text-sm text-text-secondary truncate max-w-xs">{{ template.title_template }}</td>
              <td class="py-3 px-4">
                <div class="flex gap-2">
                  <button
                    @click="editTemplate(template)"
                    class="text-primary hover:text-blue-400 text-sm"
                  >
                    编辑
                  </button>
                  <button
                    @click="sendTemplateTest(template)"
                    class="text-success hover:text-green-400 text-sm"
                    :disabled="testingSending"
                  >
                    发送测试
                  </button>
                  <button
                    @click="openSoundSettings(template)"
                    class="text-warning hover:text-yellow-400 text-sm"
                  >
                    声音设置
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="templates.length === 0" class="text-center py-8 text-text-secondary">
          暂无模板数据
        </div>
      </div>
    </div>

    <!-- 发送日志 -->
    <div class="card">
      <h2 class="text-xl font-bold mb-4">发送日志</h2>

      <div class="flex space-x-3 mb-4">
        <select
          v-model="logFilters.service_type"
          class="px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
        >
          <option value="">全部服务</option>
          <option value="feishu">飞书</option>
          <option value="email">邮件</option>
          <option value="sms">短信</option>
        </select>
        <select
          v-model="logFilters.status"
          class="px-3 py-2 bg-dark-300 border border-border-primary rounded focus:outline-none focus:border-primary"
        >
          <option value="">全部状态</option>
          <option value="sent">已发送</option>
          <option value="failed">失败</option>
        </select>
        <button @click="loadLogs" class="btn-primary">
          <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          查询
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-border-primary">
              <th class="text-left py-3 px-4">模板</th>
              <th class="text-left py-3 px-4">服务</th>
              <th class="text-left py-3 px-4">接收者</th>
              <th class="text-left py-3 px-4">标题</th>
              <th class="text-left py-3 px-4">状态</th>
              <th class="text-left py-3 px-4">创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="log in logs"
              :key="log.log_id"
              class="border-b border-border-secondary hover:bg-dark-50"
            >
              <td class="py-3 px-4 text-sm">{{ log.template_key }}</td>
              <td class="py-3 px-4 text-sm">{{ log.service_type }}</td>
              <td class="py-3 px-4 text-sm text-text-secondary truncate max-w-xs">{{ log.recipient }}</td>
              <td class="py-3 px-4 text-sm truncate max-w-xs">{{ log.title }}</td>
              <td class="py-3 px-4">
                <span
                  :class="['px-2 py-1 rounded text-xs', log.status === 'sent' ? 'bg-success/20 text-success' : 'bg-danger/20 text-danger']"
                >
                  {{ log.status === 'sent' ? '已发送' : '失败' }}
                </span>
              </td>
              <td class="py-3 px-4 text-sm text-text-secondary">{{ formatDateTime(log.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="logs.length === 0" class="text-center py-8 text-text-secondary">
          暂无日志数据
        </div>
      </div>
    </div>

    <!-- 编辑模板对话框 -->
    <div
      v-if="editDialogVisible"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="editDialogVisible = false"
    >
      <div class="bg-dark-100 rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-xl font-bold">编辑模板</h3>
          <button
            @click="editDialogVisible = false"
            class="text-text-secondary hover:text-text-primary"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">模板名称</label>
            <input
              v-model="editingTemplate.template_name"
              type="text"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入模板名称"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">标题模板</label>
            <input
              v-model="editingTemplate.title_template"
              type="text"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入标题模板"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">内容模板</label>
            <textarea
              v-model="editingTemplate.content_template"
              rows="8"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary"
              placeholder="输入内容模板"
            ></textarea>
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">优先级</label>
            <select
              v-model="editingTemplate.priority"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary"
            >
              <option :value="1">低</option>
              <option :value="2">中</option>
              <option :value="3">高</option>
              <option :value="4">紧急</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">通知渠道</label>
            <div class="space-y-2">
              <label class="flex items-center">
                <input
                  v-model="editingTemplate.enable_feishu"
                  type="checkbox"
                  class="mr-2"
                />
                <span>飞书</span>
              </label>
              <label class="flex items-center">
                <input
                  v-model="editingTemplate.enable_email"
                  type="checkbox"
                  class="mr-2"
                />
                <span>邮件</span>
              </label>
              <label class="flex items-center">
                <input
                  v-model="editingTemplate.enable_sms"
                  type="checkbox"
                  class="mr-2"
                />
                <span>短信</span>
              </label>
            </div>
          </div>
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button @click="editDialogVisible = false" class="btn-secondary">
            取消
          </button>
          <button @click="saveTemplate" class="btn-primary" :disabled="savingTemplate">
            {{ savingTemplate ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 声音设置对话框 -->
    <div
      v-if="soundDialogVisible"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      @click.self="soundDialogVisible = false"
    >
      <div class="bg-dark-100 rounded-lg p-6 max-w-md w-full mx-4">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-xl font-bold">声音提醒设置</h3>
          <button
            @click="soundDialogVisible = false"
            class="text-text-secondary hover:text-text-primary"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- 全系统共用提示 -->
        <div class="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded">
          <div class="flex items-start gap-2">
            <svg class="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div class="text-sm text-blue-300">
              <strong>系统级设置：</strong>此声音设置对所有用户生效，修改后将影响所有接收此类通知的用户。
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">模板名称</label>
            <div class="text-text-primary">{{ soundSettingTemplate.template_name }}</div>
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">提醒声音</label>
            <select
              v-model="soundSettingTemplate.alert_sound"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary"
            >
              <option value="">默认声音</option>
              <option v-for="sound in availableSounds" :key="sound.filename" :value="sound.filename">
                {{ sound.filename }}
              </option>
            </select>
          </div>

          <div v-if="soundSettingTemplate.alert_sound">
            <button
              @click="playSelectedSound"
              class="btn-secondary w-full"
            >
              <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
              </svg>
              试听声音
            </button>
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">重复次数</label>
            <input
              v-model.number="soundSettingTemplate.repeat_count"
              type="number"
              min="1"
              max="10"
              class="w-full px-3 py-2 bg-dark-200 border border-border-primary rounded focus:outline-none focus:border-primary"
            />
          </div>
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button @click="soundDialogVisible = false" class="btn-secondary">
            取消
          </button>
          <button @click="saveSoundSettings" class="btn-primary" :disabled="savingSoundSettings">
            {{ savingSoundSettings ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '@/services/api'
import { formatDateTimeBeijing } from '@/utils/timeUtils'

const saving = ref(false)
const testing = ref(false)
const testingSending = ref(false)
const showSecret = ref(false)

// 用户列表
const users = ref([])
const selectedUserId = ref('')
const selectedUserInfo = ref('')

// 过滤有飞书数据的用户
const usersWithFeishu = computed(() => {
  return users.value.filter(u => u.feishu_open_id || u.feishu_mobile || u.email)
})

// 飞书配置
const feishuConfig = ref({
  is_enabled: false,
  app_id: 'cli_a9235819f078dcbd',
  app_secret: ''
})
const testRecipient = ref('')

// 模板管理
const templateCategory = ref('')
const categories = [
  { label: '全部', value: '' },
  { label: '交易类', value: 'trading' },
  { label: '风险类', value: 'risk' },
  { label: '系统类', value: 'system' }
]
const templates = ref([])
const editDialogVisible = ref(false)
const editingTemplate = ref({})
const savingTemplate = ref(false)

// 声音设置
const soundDialogVisible = ref(false)
const soundSettingTemplate = ref({})
const savingSoundSettings = ref(false)
const availableSounds = ref([])
const currentAudio = ref(null)

// 日志查询
const logFilters = ref({
  service_type: '',
  status: ''
})
const logs = ref([])

onMounted(async () => {
  await loadConfigs()
  await loadTemplates()
  await loadUsers()
  await loadAvailableSounds()
})

async function loadUsers() {
  try {
    const response = await api.get('/api/v1/users')
    console.log('Users API response:', response.data)
    users.value = response.data.users || response.data || []
    console.log('Loaded users:', users.value.length, users.value)
  } catch (error) {
    console.error('加载用户列表失败:', error)
    alert('加载用户列表失败')
  }
}

async function refreshUsers() {
  await loadUsers()
  alert('用户列表已刷新')
}

function onUserSelect() {
  const user = users.value.find(u => u.user_id === selectedUserId.value)
  if (user) {
    // 优先使用 feishu_open_id，其次 feishu_mobile，最后 email
    if (user.feishu_open_id) {
      testRecipient.value = user.feishu_open_id
      selectedUserInfo.value = `${user.username} (Open ID: ${user.feishu_open_id.substring(0, 20)}...)`
    } else if (user.feishu_mobile) {
      testRecipient.value = user.feishu_mobile
      selectedUserInfo.value = `${user.username} (手机: ${user.feishu_mobile})`
    } else if (user.email) {
      testRecipient.value = user.email
      selectedUserInfo.value = `${user.username} (邮箱: ${user.email})`
    } else {
      testRecipient.value = ''
      selectedUserInfo.value = ''
      alert('该用户未配置飞书信息')
    }
  }
}

async function loadConfigs() {
  try {
    const response = await api.get('/api/v1/notifications/config')
    const configs = response.data.configs

    const feishu = configs.find(c => c.service_type === 'feishu')
    if (feishu) {
      feishuConfig.value = {
        is_enabled: feishu.is_enabled,
        app_id: feishu.config_data.app_id || 'cli_a9235819f078dcbd',
        app_secret: feishu.config_data.app_secret || ''
      }
    }
  } catch (error) {
    console.error('加载配置失败:', error)
    alert('加载配置失败')
  }
}

async function saveConfig(serviceType) {
  saving.value = true
  try {
    const config = {
      is_enabled: feishuConfig.value.is_enabled,
      config_data: {
        app_id: feishuConfig.value.app_id,
        app_secret: feishuConfig.value.app_secret
      }
    }

    await api.put(`/api/v1/notifications/config/${serviceType}`, config)
    alert('配置保存成功')
  } catch (error) {
    alert(error.response?.data?.detail || '配置保存失败')
  } finally {
    saving.value = false
  }
}

async function testNotification(serviceType) {
  testing.value = true
  try {
    const response = await api.post(`/api/v1/notifications/test/${serviceType}?recipient=${testRecipient.value}`)

    if (response.data.success) {
      alert('测试消息发送成功！请检查接收端')
    } else {
      alert(`发送失败: ${response.data.error}`)
    }
  } catch (error) {
    alert(error.response?.data?.detail || '发送测试消息失败')
  } finally {
    testing.value = false
  }
}

async function loadTemplates() {
  try {
    const params = templateCategory.value ? { category: templateCategory.value } : {}
    const response = await api.get('/api/v1/notifications/templates', { params })
    templates.value = response.data.templates
  } catch (error) {
    console.error('加载模板失败:', error)
    alert('加载模板失败')
  }
}

// 编辑模板
function editTemplate(template) {
  editingTemplate.value = { ...template }
  editDialogVisible.value = true
}

async function saveTemplate() {
  savingTemplate.value = true
  try {
    await api.put(`/api/v1/notifications/templates/${editingTemplate.value.template_id}`, editingTemplate.value)
    alert('模板保存成功')
    editDialogVisible.value = false
    await loadTemplates()
  } catch (error) {
    console.error('保存模板失败:', error)
    alert(error.response?.data?.detail || '保存模板失败')
  } finally {
    savingTemplate.value = false
  }
}

// 声音设置
async function loadAvailableSounds() {
  try {
    const response = await api.get('/api/v1/sounds')
    availableSounds.value = response.data.sounds || []
  } catch (error) {
    console.error('加载声音文件失败:', error)
    availableSounds.value = []
  }
}

function openSoundSettings(template) {
  soundSettingTemplate.value = {
    ...template,
    alert_sound: template.alert_sound || '',
    repeat_count: template.repeat_count || 3
  }
  soundDialogVisible.value = true
}

function playSelectedSound() {
  if (!soundSettingTemplate.value.alert_sound) return

  // Stop current audio if playing
  if (currentAudio.value) {
    currentAudio.value.pause()
    currentAudio.value = null
  }

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://13.115.21.77:8000'
  const soundUrl = `${apiBaseUrl}/sounds/${soundSettingTemplate.value.alert_sound}`

  currentAudio.value = new Audio(soundUrl)
  currentAudio.value.play().catch(error => {
    console.error('播放声音失败:', error)
    alert('播放声音失败')
  })
}

async function saveSoundSettings() {
  savingSoundSettings.value = true
  try {
    await api.put(`/api/v1/notifications/templates/${soundSettingTemplate.value.template_id}`, {
      alert_sound: soundSettingTemplate.value.alert_sound,
      repeat_count: soundSettingTemplate.value.repeat_count
    })
    alert('声音设置保存成功')
    soundDialogVisible.value = false
    await loadTemplates()
  } catch (error) {
    console.error('保存声音设置失败:', error)
    alert(error.response?.data?.detail || '保存声音设置失败')
  } finally {
    savingSoundSettings.value = false
  }
}

async function sendTemplateTest(template) {
  testingSending.value = true
  try {
    console.log('Sending template test for:', template.template_key)

    // Get current user info from API
    const userResponse = await api.get('/api/v1/users/me')
    const currentUser = userResponse.data
    console.log('Current user:', currentUser)

    // Check if user has Feishu info
    if (!currentUser.feishu_open_id && !currentUser.feishu_mobile && !currentUser.email) {
      alert('当前用户未配置飞书信息，无法发送测试消息')
      return
    }

    console.log('Sending to user:', currentUser.username)

    // Provide comprehensive test variables to cover most templates
    const testVariables = {
      user_name: currentUser.username,
      timestamp: new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }),
      test_value: '测试数据',
      // Trading related variables
      exchange: 'Binance',
      symbol: 'BTCUSDT',
      side: 'BUY',
      quantity: '0.001',
      price: '50000.00',
      spread: '10.50',
      profit: '100.00',
      loss: '50.00',
      current_profit: '150.00',
      total_profit: '500.00',
      // Account related variables
      account_name: 'Test Account',
      balance: '10000.00',
      equity: '10500.00',
      margin: '1000.00',
      net_asset: '10500.00',
      // Risk related variables
      risk_level: '低',
      risk_ratio: '25.5',
      // System related variables
      system_name: '交易系统',
      status: '正常',
      message: '这是一条测试消息',
      // Time related variables
      duration: '5分钟',
      time: new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }),
      date: new Date().toLocaleDateString('zh-CN'),
      // Position related variables
      position_id: 'TEST123',
      position_type: '多头',
      entry_price: '50000.00',
      current_price: '50500.00',
      pnl: '500.00',
      // Alert related variables
      alert_type: '测试警报',
      alert_level: '中',
      threshold: '100.00',
      current_value: '150.00',
      // Strategy related variables
      strategy_name: '套利策略',
      strategy_type: '正向套利',
      action: '开仓',
      // Order related variables
      order_id: 'ORDER123',
      order_type: '限价单',
      order_status: '已成交',
      filled_qty: '0.001',
      unfilled_qty: '0.000',
      // Exchange specific
      binance_filled: '0.001',
      bybit_filled: '0.001',
      binance_price: '50000.00',
      bybit_price: '50010.50',
      // Additional common variables
      amount: '1000.00',
      fee: '0.50',
      rate: '0.05',
      percentage: '5.0',
      count: '10',
      total: '10000.00'
    }

    // Send notification using the template
    const response = await api.post('/api/v1/notifications/send', {
      template_key: template.template_key,
      user_ids: [String(currentUser.user_id)],
      variables: testVariables
    })

    console.log('Send response:', response.data)

    if (response.data.success) {
      alert(`测试消息已发送到 ${currentUser.username}`)
      // Reload logs to show the new test message
      await loadLogs()
    } else {
      alert('发送测试消息失败')
    }
  } catch (error) {
    console.error('发送测试消息失败:', error)
    console.error('Error details:', error.response?.data)

    let errorMsg = '发送测试消息失败'
    if (error.response?.data?.detail) {
      errorMsg = error.response.data.detail
    }
    alert(errorMsg)
  } finally {
    testingSending.value = false
  }
}

async function loadLogs() {
  try {
    const response = await api.get('/api/v1/notifications/logs', {
      params: {
        service_type: logFilters.value.service_type || undefined,
        status: logFilters.value.status || undefined,
        limit: 50
      }
    })
    logs.value = response.data.logs
  } catch (error) {
    console.error('加载日志失败:', error)
    alert('加载日志失败')
  }
}

function getCategoryClass(category) {
  const classes = {
    trading: 'bg-success/20 text-success',
    risk: 'bg-warning/20 text-warning',
    system: 'bg-blue-500/20 text-blue-400'
  }
  return classes[category] || 'bg-dark-300 text-text-secondary'
}

function getCategoryLabel(category) {
  const labels = {
    trading: '交易类',
    risk: '风险类',
    system: '系统类'
  }
  return labels[category] || category
}

function getPriorityClass(priority) {
  const classes = {
    4: 'bg-danger/20 text-danger',
    3: 'bg-warning/20 text-warning',
    2: 'bg-blue-500/20 text-blue-400',
    1: 'bg-success/20 text-success'
  }
  return classes[priority] || 'bg-dark-300 text-text-secondary'
}

function getPriorityLabel(priority) {
  const labels = {
    4: '紧急',
    3: '高',
    2: '中',
    1: '低'
  }
  return labels[priority] || priority
}

function formatDateTime(dateStr) {
  return formatDateTimeBeijing(dateStr)
}
</script>
