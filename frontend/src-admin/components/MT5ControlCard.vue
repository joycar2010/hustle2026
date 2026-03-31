<template>
  <el-card class="mt5-control-card">
    <template #header>
      <div class="card-header">
        <span class="client-name">{{ client.client_name }}</span>
        <el-tag :type="statusTagType" size="large">
          <el-icon v-if="isRunning"><CircleCheck /></el-icon>
          <el-icon v-else><CircleClose /></el-icon>
          {{ statusText }}
        </el-tag>
      </div>
    </template>

    <!-- 基本信息 -->
    <div class="client-info">
      <el-descriptions :column="2" size="small" border>
        <el-descriptions-item label="MT5 账号">
          {{ client.mt5_login }}
        </el-descriptions-item>
        <el-descriptions-item label="服务器">
          {{ client.mt5_server }}
        </el-descriptions-item>
        <el-descriptions-item label="客户端路径" :span="2">
          <el-text size="small" type="info">{{ client.mt5_path }}</el-text>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 健康状态 -->
    <div v-if="healthStatus && isRunning" class="health-status">
      <el-divider content-position="left">
        <el-icon><Monitor /></el-icon>
        健康状态
      </el-divider>

      <div class="health-metrics">
        <!-- CPU 使用率 -->
        <div class="metric-item">
          <div class="metric-label">
            <el-icon><Cpu /></el-icon>
            <span>CPU 使用率</span>
          </div>
          <el-progress
            :percentage="Math.round(healthStatus.details?.cpu_percent || 0)"
            :status="healthStatus.cpu_high ? 'exception' : 'success'"
            :stroke-width="12"
          >
            <span class="metric-value">
              {{ healthStatus.details?.cpu_percent?.toFixed(1) || 0 }}%
            </span>
          </el-progress>
        </div>

        <!-- 内存使用率 -->
        <div class="metric-item">
          <div class="metric-label">
            <el-icon><Memo /></el-icon>
            <span>内存使用</span>
          </div>
          <el-progress
            :percentage="Math.round(healthStatus.details?.memory_percent || 0)"
            :status="healthStatus.memory_high ? 'exception' : 'success'"
            :stroke-width="12"
          >
            <span class="metric-value">
              {{ healthStatus.details?.memory_mb?.toFixed(0) || 0 }} MB
              ({{ healthStatus.details?.memory_percent?.toFixed(1) || 0 }}%)
            </span>
          </el-progress>
        </div>

        <!-- 进程信息 -->
        <div class="process-info">
          <el-space wrap>
            <el-tag size="small">PID: {{ healthStatus.details?.pid }}</el-tag>
            <el-tag size="small">线程: {{ healthStatus.details?.num_threads }}</el-tag>
            <el-tag size="small">状态: {{ healthStatus.details?.status }}</el-tag>
          </el-space>
        </div>

        <!-- 告警标签 -->
        <div v-if="hasAlerts" class="alerts">
          <el-alert
            v-if="healthStatus.is_frozen"
            title="检测到卡顿"
            type="error"
            :closable="false"
            show-icon
          >
            MT5 客户端可能已卡顿，建议重启
          </el-alert>
          <el-alert
            v-if="healthStatus.cpu_high"
            title="CPU 使用率过高"
            type="warning"
            :closable="false"
            show-icon
          >
            CPU 使用率超过 {{ monitoringConfig.cpu_threshold }}%
          </el-alert>
          <el-alert
            v-if="healthStatus.memory_high"
            title="内存使用率过高"
            type="warning"
            :closable="false"
            show-icon
          >
            内存使用率超过 {{ monitoringConfig.memory_threshold }}%
          </el-alert>
        </div>
      </div>
    </div>

    <!-- 控制按钮 -->
    <div class="control-buttons">
      <el-button-group>
        <el-button
          type="success"
          :icon="VideoPlay"
          :disabled="isRunning || loading"
          :loading="loading === 'start'"
          @click="handleStart"
        >
          启动
        </el-button>
        <el-button
          type="danger"
          :icon="VideoPause"
          :disabled="!isRunning || loading"
          :loading="loading === 'stop'"
          @click="handleStop"
        >
          停止
        </el-button>
        <el-button
          type="warning"
          :icon="RefreshRight"
          :disabled="!isRunning || loading"
          :loading="loading === 'restart'"
          @click="handleRestart"
        >
          重启
        </el-button>
      </el-button-group>

      <el-button
        :icon="Refresh"
        :disabled="loading"
        @click="fetchStatus"
      >
        刷新状态
      </el-button>
    </div>

    <!-- 最后更新时间 -->
    <div class="last-update">
      <el-text size="small" type="info">
        最后更新: {{ lastUpdateTime }}
      </el-text>
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  VideoPlay,
  VideoPause,
  RefreshRight,
  Refresh,
  CircleCheck,
  CircleClose,
  Monitor,
  Cpu,
  Memo
} from '@element-plus/icons-vue'
import api from '@/utils/api'

const props = defineProps({
  client: {
    type: Object,
    required: true
  }
})

const isRunning = ref(false)
const healthStatus = ref(null)
const loading = ref(null)
const lastUpdateTime = ref('--')
const monitoringConfig = ref({
  cpu_threshold: 95,
  memory_threshold: 90
})

let refreshTimer = null

const statusText = computed(() => {
  if (loading.value) return '操作中...'
  return isRunning.value ? '运行中' : '已停止'
})

const statusTagType = computed(() => {
  if (loading.value) return 'info'
  if (!isRunning.value) return 'info'
  if (hasAlerts.value) return 'danger'
  return 'success'
})

const hasAlerts = computed(() => {
  if (!healthStatus.value) return false
  return healthStatus.value.is_frozen ||
         healthStatus.value.cpu_high ||
         healthStatus.value.memory_high
})

// 使用 agent_instance_name 字段，如果没有则从 client_name 生成
const instanceName = computed(() => {
  if (props.client.agent_instance_name) {
    return props.client.agent_instance_name
  }
  // 回退：将中文和特殊字符转换为下划线
  return props.client.client_name
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
})

async function fetchStatus() {
  try {
    const response = await api.get(`/api/v1/mt5-agent/instances/${instanceName.value}`)
    isRunning.value = response.is_running
    healthStatus.value = response.health_status
    lastUpdateTime.value = new Date().toLocaleTimeString('zh-CN')
  } catch (error) {
    console.error('Failed to fetch status:', error)
    // 如果是 Agent 不可用，显示离线状态
    if (error.response?.status === 503) {
      isRunning.value = false
      healthStatus.value = null
      ElMessage.warning('MT5 Agent 服务不可用')
    }
  }
}

async function handleStart() {
  try {
    await ElMessageBox.confirm(
      `确定要启动 ${props.client.client_name} 吗？`,
      '确认启动',
      {
        type: 'warning',
        confirmButtonText: '启动',
        cancelButtonText: '取消'
      }
    )

    loading.value = 'start'
    const response = await api.post(
      `/api/v1/mt5-agent/instances/${instanceName.value}/start`,
      null,
      { params: { wait_seconds: 5 } }
    )

    if (response.success) {
      ElMessage.success({
        message: '启动成功',
        duration: 3000
      })
      // 等待 3 秒后刷新状态
      setTimeout(fetchStatus, 3000)
    } else {
      ElMessage.error(`启动失败: ${response.message}`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('启动失败，请检查 MT5 Agent 服务')
      console.error('Start failed:', error)
    }
  } finally {
    loading.value = null
  }
}

async function handleStop() {
  try {
    await ElMessageBox.confirm(
      `确定要停止 ${props.client.client_name} 吗？这将关闭 MT5 客户端。`,
      '确认停止',
      {
        type: 'warning',
        confirmButtonText: '停止',
        cancelButtonText: '取消'
      }
    )

    loading.value = 'stop'
    const response = await api.post(
      `/api/v1/mt5-agent/instances/${instanceName.value}/stop`,
      null,
      { params: { force: true } }
    )

    if (response.success) {
      ElMessage.success({
        message: '停止成功',
        duration: 3000
      })
      await fetchStatus()
    } else {
      ElMessage.error(`停止失败: ${response.message}`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('停止失败，请检查 MT5 Agent 服务')
      console.error('Stop failed:', error)
    }
  } finally {
    loading.value = null
  }
}

async function handleRestart() {
  try {
    await ElMessageBox.confirm(
      `确定要重启 ${props.client.client_name} 吗？这将关闭并重新启动 MT5 客户端。`,
      '确认重启',
      {
        type: 'warning',
        confirmButtonText: '重启',
        cancelButtonText: '取消'
      }
    )

    loading.value = 'restart'
    const response = await api.post(
      `/api/v1/mt5-agent/instances/${instanceName.value}/restart`,
      null,
      { params: { wait_seconds: 5 } }
    )

    if (response.success) {
      ElMessage.success({
        message: '重启成功',
        duration: 3000
      })
      // 等待 5 秒后刷新状态
      setTimeout(fetchStatus, 5000)
    } else {
      ElMessage.error(`重启失败: ${response.message}`)
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('重启失败，请检查 MT5 Agent 服务')
      console.error('Restart failed:', error)
    }
  } finally {
    loading.value = null
  }
}

onMounted(() => {
  fetchStatus()
  // 每 30 秒自动刷新状态
  refreshTimer = setInterval(fetchStatus, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.mt5-control-card {
  margin-bottom: 20px;
  border-radius: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.client-name {
  font-size: 16px;
  font-weight: 600;
}

.client-info {
  margin-bottom: 20px;
}

.health-status {
  margin: 20px 0;
}

.health-metrics {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metric-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  color: #606266;
}

.metric-value {
  font-size: 12px;
  font-weight: 600;
}

.process-info {
  padding: 8px 0;
}

.alerts {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.control-buttons {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}

.last-update {
  margin-top: 12px;
  text-align: right;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .control-buttons {
    flex-direction: column;
    gap: 12px;
  }

  .control-buttons .el-button-group {
    width: 100%;
  }

  .control-buttons .el-button-group .el-button {
    flex: 1;
  }
}
</style>
