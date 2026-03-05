<template>
  <div class="notification-service-config">
    <el-tabs v-model="activeTab" class="config-tabs">
      <!-- 飞书配置 -->
      <el-tab-pane label="飞书配置" name="feishu">
        <el-card class="config-card">
          <template #header>
            <div class="card-header">
              <span>飞书机器人配置</span>
              <el-switch
                v-model="feishuConfig.is_enabled"
                active-text="已启用"
                inactive-text="已禁用"
              />
            </div>
          </template>

          <el-form :model="feishuConfig" label-width="120px">
            <el-form-item label="App ID">
              <el-input
                v-model="feishuConfig.app_id"
                placeholder="cli_a9235819f078dcbd"
                :disabled="!feishuConfig.is_enabled"
              />
              <div class="form-tip">飞书开放平台应用凭证</div>
            </el-form-item>

            <el-form-item label="App Secret">
              <el-input
                v-model="feishuConfig.app_secret"
                type="password"
                show-password
                placeholder="请输入App Secret"
                :disabled="!feishuConfig.is_enabled"
              />
              <div class="form-tip">请妥善保管，不要泄露</div>
            </el-form-item>

            <el-form-item label="测试接收人">
              <el-input
                v-model="testRecipient"
                placeholder="飞书open_id或邮箱"
              />
              <div class="form-tip">用于测试消息发送</div>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                @click="saveConfig('feishu')"
                :loading="saving"
              >
                保存配置
              </el-button>
              <el-button
                @click="testNotification('feishu')"
                :loading="testing"
                :disabled="!feishuConfig.is_enabled || !testRecipient"
              >
                发送测试消息
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 邮件配置 -->
      <el-tab-pane label="邮件配置" name="email">
        <el-card class="config-card">
          <template #header>
            <div class="card-header">
              <span>邮件服务配置</span>
              <el-switch
                v-model="emailConfig.is_enabled"
                active-text="已启用"
                inactive-text="已禁用"
              />
            </div>
          </template>

          <el-form :model="emailConfig" label-width="120px">
            <el-form-item label="SMTP服务器">
              <el-input
                v-model="emailConfig.smtp_host"
                placeholder="smtp.gmail.com"
                :disabled="!emailConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item label="SMTP端口">
              <el-input-number
                v-model="emailConfig.smtp_port"
                :min="1"
                :max="65535"
                :disabled="!emailConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item label="发件邮箱">
              <el-input
                v-model="emailConfig.from_email"
                placeholder="noreply@example.com"
                :disabled="!emailConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item label="用户名">
              <el-input
                v-model="emailConfig.username"
                :disabled="!emailConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item label="密码">
              <el-input
                v-model="emailConfig.password"
                type="password"
                show-password
                :disabled="!emailConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                @click="saveConfig('email')"
                :loading="saving"
              >
                保存配置
              </el-button>
              <el-button disabled>
                发送测试邮件（暂未实现）
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 短信配置 -->
      <el-tab-pane label="短信配置" name="sms">
        <el-card class="config-card">
          <template #header>
            <div class="card-header">
              <span>短信服务配置</span>
              <el-switch
                v-model="smsConfig.is_enabled"
                active-text="已启用"
                inactive-text="已禁用"
              />
            </div>
          </template>

          <el-form :model="smsConfig" label-width="120px">
            <el-form-item label="服务商">
              <el-select
                v-model="smsConfig.provider"
                :disabled="!smsConfig.is_enabled"
              >
                <el-option label="阿里云" value="aliyun" />
                <el-option label="腾讯云" value="tencent" />
              </el-select>
            </el-form-item>

            <el-form-item label="Access Key">
              <el-input
                v-model="smsConfig.access_key"
                :disabled="!smsConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item label="Access Secret">
              <el-input
                v-model="smsConfig.access_secret"
                type="password"
                show-password
                :disabled="!smsConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item label="签名">
              <el-input
                v-model="smsConfig.sign_name"
                placeholder="配送服务"
                :disabled="!smsConfig.is_enabled"
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                @click="saveConfig('sms')"
                :loading="saving"
              >
                保存配置
              </el-button>
              <el-button disabled>
                发送测试短信（暂未实现）
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 通知模板 -->
      <el-tab-pane label="通知模板" name="templates">
        <div class="template-filters">
          <el-radio-group v-model="templateCategory" @change="loadTemplates">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="trading">交易类</el-radio-button>
            <el-radio-button label="risk">风险类</el-radio-button>
            <el-radio-button label="system">系统类</el-radio-button>
          </el-radio-group>
        </div>

        <el-table :data="templates" style="width: 100%" v-loading="loadingTemplates">
          <el-table-column prop="template_name" label="模板名称" width="150" />
          <el-table-column prop="category" label="分类" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.category === 'trading'" type="success">交易类</el-tag>
              <el-tag v-else-if="row.category === 'risk'" type="warning">风险类</el-tag>
              <el-tag v-else type="info">系统类</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="通知渠道" width="150">
            <template #default="{ row }">
              <el-tag v-if="row.enable_feishu" type="success" size="small" class="channel-tag">飞书</el-tag>
              <el-tag v-if="row.enable_email" type="info" size="small" class="channel-tag">邮件</el-tag>
              <el-tag v-if="row.enable_sms" type="warning" size="small" class="channel-tag">短信</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="priority" label="优先级" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.priority === 4" type="danger" size="small">紧急</el-tag>
              <el-tag v-else-if="row.priority === 3" type="warning" size="small">高</el-tag>
              <el-tag v-else-if="row.priority === 2" type="info" size="small">中</el-tag>
              <el-tag v-else type="success" size="small">低</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="title_template" label="标题模板" show-overflow-tooltip />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="editTemplate(row)">编辑</el-button>
              <el-button size="small" type="primary" @click="previewTemplate(row)">预览</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 发送日志 -->
      <el-tab-pane label="发送日志" name="logs">
        <div class="log-filters">
          <el-select v-model="logFilters.service_type" placeholder="服务类型" clearable style="width: 150px">
            <el-option label="飞书" value="feishu" />
            <el-option label="邮件" value="email" />
            <el-option label="短信" value="sms" />
          </el-select>
          <el-select v-model="logFilters.status" placeholder="状态" clearable style="width: 150px">
            <el-option label="已发送" value="sent" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-button type="primary" @click="loadLogs">查询</el-button>
        </div>

        <el-table :data="logs" style="width: 100%" v-loading="loadingLogs">
          <el-table-column prop="template_key" label="模板" width="150" />
          <el-table-column prop="service_type" label="服务" width="100" />
          <el-table-column prop="recipient" label="接收者" width="200" show-overflow-tooltip />
          <el-table-column prop="title" label="标题" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.status === 'sent'" type="success" size="small">已发送</el-tag>
              <el-tag v-else type="danger" size="small">失败</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.created_at) }}
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 模板编辑对话框 -->
    <el-dialog
      v-model="editDialogVisible"
      title="编辑通知模板"
      width="800px"
    >
      <el-form :model="editingTemplate" label-width="120px">
        <el-form-item label="模板名称">
          <el-input v-model="editingTemplate.template_name" />
        </el-form-item>
        <el-form-item label="标题模板">
          <el-input v-model="editingTemplate.title_template" />
          <div class="form-tip">支持变量：{order_id}, {quantity}, {time} 等</div>
        </el-form-item>
        <el-form-item label="内容模板">
          <el-input
            v-model="editingTemplate.content_template"
            type="textarea"
            :rows="6"
          />
        </el-form-item>
        <el-form-item label="通知渠道">
          <el-checkbox v-model="editingTemplate.enable_feishu">飞书</el-checkbox>
          <el-checkbox v-model="editingTemplate.enable_email">邮件</el-checkbox>
          <el-checkbox v-model="editingTemplate.enable_sms">短信</el-checkbox>
        </el-form-item>
        <el-form-item label="优先级">
          <el-radio-group v-model="editingTemplate.priority">
            <el-radio :label="1">低</el-radio>
            <el-radio :label="2">中</el-radio>
            <el-radio :label="3">高</el-radio>
            <el-radio :label="4">紧急</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTemplate" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatDateTimeBeijing } from '@/utils/timeUtils'

const activeTab = ref('feishu')
const saving = ref(false)
const testing = ref(false)
const loadingTemplates = ref(false)
const loadingLogs = ref(false)

// 飞书配置
const feishuConfig = ref({
  is_enabled: false,
  app_id: 'cli_a9235819f078dcbd',
  app_secret: ''
})
const testRecipient = ref('')

// 邮件配置
const emailConfig = ref({
  is_enabled: false,
  smtp_host: 'smtp.gmail.com',
  smtp_port: 587,
  from_email: '',
  username: '',
  password: ''
})

// 短信配置
const smsConfig = ref({
  is_enabled: false,
  provider: 'aliyun',
  access_key: '',
  access_secret: '',
  sign_name: ''
})

// 模板管理
const templateCategory = ref('')
const templates = ref([])
const editDialogVisible = ref(false)
const editingTemplate = ref({})

// 日志查询
const logFilters = ref({
  service_type: '',
  status: ''
})
const logs = ref([])

onMounted(async () => {
  await loadConfigs()
  await loadTemplates()
})

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

    const email = configs.find(c => c.service_type === 'email')
    if (email) {
      emailConfig.value = {
        is_enabled: email.is_enabled,
        ...email.config_data
      }
    }

    const sms = configs.find(c => c.service_type === 'sms')
    if (sms) {
      smsConfig.value = {
        is_enabled: sms.is_enabled,
        ...sms.config_data
      }
    }
  } catch (error) {
    ElMessage.error('加载配置失败')
  }
}

async function saveConfig(serviceType) {
  saving.value = true
  try {
    let config
    if (serviceType === 'feishu') {
      config = {
        is_enabled: feishuConfig.value.is_enabled,
        config_data: {
          app_id: feishuConfig.value.app_id,
          app_secret: feishuConfig.value.app_secret
        }
      }
    } else if (serviceType === 'email') {
      config = {
        is_enabled: emailConfig.value.is_enabled,
        config_data: {
          smtp_host: emailConfig.value.smtp_host,
          smtp_port: emailConfig.value.smtp_port,
          from_email: emailConfig.value.from_email,
          username: emailConfig.value.username,
          password: emailConfig.value.password
        }
      }
    } else if (serviceType === 'sms') {
      config = {
        is_enabled: smsConfig.value.is_enabled,
        config_data: {
          provider: smsConfig.value.provider,
          access_key: smsConfig.value.access_key,
          access_secret: smsConfig.value.access_secret,
          sign_name: smsConfig.value.sign_name
        }
      }
    }

    await api.put(`/api/v1/notifications/config/${serviceType}`, config)
    ElMessage.success('配置保存成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '配置保存失败')
  } finally {
    saving.value = false
  }
}

async function testNotification(serviceType) {
  testing.value = true
  try {
    const response = await api.post(`/api/v1/notifications/test/${serviceType}?recipient=${testRecipient.value}`)

    if (response.data.success) {
      ElMessage.success('测试消息发送成功！请检查接收端')
    } else {
      ElMessage.error(`发送失败: ${response.data.error}`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '发送测试消息失败')
  } finally {
    testing.value = false
  }
}

async function loadTemplates() {
  loadingTemplates.value = true
  try {
    const params = templateCategory.value ? { category: templateCategory.value } : {}
    const response = await api.get('/api/v1/notifications/templates', { params })
    templates.value = response.data.templates
  } catch (error) {
    ElMessage.error('加载模板失败')
  } finally {
    loadingTemplates.value = false
  }
}

function editTemplate(template) {
  editingTemplate.value = { ...template }
  editDialogVisible.value = true
}

async function saveTemplate() {
  saving.value = true
  try {
    await api.put(`/api/v1/notifications/templates/${editingTemplate.value.template_id}`, editingTemplate.value)
    ElMessage.success('模板保存成功')
    editDialogVisible.value = false
    await loadTemplates()
  } catch (error) {
    ElMessage.error('模板保存失败')
  } finally {
    saving.value = false
  }
}

function previewTemplate(template) {
  ElMessageBox.alert(
    `<strong>标题：</strong>${template.title_template}<br><br><strong>内容：</strong><pre>${template.content_template}</pre>`,
    '模板预览',
    {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '关闭'
    }
  )
}

async function loadLogs() {
  loadingLogs.value = true
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
    ElMessage.error('加载日志失败')
  } finally {
    loadingLogs.value = false
  }
}

function formatDateTime(dateStr) {
  return formatDateTimeBeijing(dateStr)
}
</script>

<style scoped>
.notification-service-config {
  padding: 20px;
}

.config-tabs {
  background: white;
  padding: 20px;
  border-radius: 8px;
}

.config-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.template-filters {
  margin-bottom: 20px;
}

.channel-tag {
  margin-right: 4px;
}

.log-filters {
  margin-bottom: 20px;
  display: flex;
  gap: 10px;
}
</style>
