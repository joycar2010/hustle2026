<template>
  <div :class="['bg-dark-200 rounded-lg border p-3 transition-all',
    instance.is_active ? 'border-primary shadow-lg shadow-primary/20' : 'border-border-primary']">
    <div class="flex items-start justify-between mb-2">
      <div class="flex-1">
        <div class="flex items-center gap-2 mb-1 flex-wrap">
          <span class="text-sm font-medium">{{ instance.instance_name }}</span>

          <!-- 实例类型标签 -->
          <span :class="['px-1.5 py-0.5 rounded text-xs font-medium',
            instance.instance_type === 'primary'
              ? 'bg-primary/10 text-primary'
              : 'bg-[#f0b90b]/10 text-[#f0b90b]']">
            {{ instance.instance_type === 'primary' ? '主跑' : '备用' }}
          </span>

          <!-- 活动标签 -->
          <span v-if="instance.is_active"
            class="px-1.5 py-0.5 rounded text-xs font-medium bg-[#0ecb81]/10 text-[#0ecb81] flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-[#0ecb81] animate-pulse"></span>
            活动
          </span>
        </div>

        <div class="text-xs text-text-tertiary space-y-0.5">
          <div class="flex items-center gap-2">
            <span>端口：</span>
            <span class="font-mono">{{ instance.service_port }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span>状态：</span>
            <span :class="getStatusClass(instance.status)" class="font-medium">
              {{ getStatusText(instance.status) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="flex gap-1 flex-wrap">
      <!-- 切换为活动 -->
      <button v-if="!instance.is_active" @click="$emit('switch')"
        class="px-2 py-1 bg-primary/10 text-primary hover:bg-primary/20 rounded text-xs transition-colors font-medium">
        切换为活动
      </button>

      <!-- 刷新状态 -->
      <button @click="$emit('refresh')"
        class="px-2 py-1 bg-dark-100 hover:bg-dark-50 text-text-secondary rounded text-xs transition-colors">
        刷新
      </button>

      <!-- 启动 -->
      <button v-if="instance.status !== 'running'" @click="$emit('control', 'start')"
        class="px-2 py-1 bg-[#0ecb81]/10 text-[#0ecb81] hover:bg-[#0ecb81]/20 rounded text-xs transition-colors">
        启动
      </button>

      <!-- 停止 -->
      <button v-if="instance.status === 'running'" @click="$emit('control', 'stop')"
        class="px-2 py-1 bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20 rounded text-xs transition-colors">
        停止
      </button>

      <!-- 重启 -->
      <button @click="$emit('control', 'restart')"
        class="px-2 py-1 bg-[#f0b90b]/10 text-[#f0b90b] hover:bg-[#f0b90b]/20 rounded text-xs transition-colors">
        重启
      </button>

      <!-- 编辑 -->
      <button @click="$emit('edit')"
        class="px-2 py-1 bg-dark-100 hover:bg-dark-50 text-text-secondary rounded text-xs transition-colors">
        编辑
      </button>

      <!-- 删除 -->
      <button @click="$emit('delete')"
        :disabled="instance.is_active"
        :class="['px-2 py-1 rounded text-xs transition-colors',
          instance.is_active
            ? 'bg-gray-600/20 text-gray-500 cursor-not-allowed'
            : 'bg-[#f6465d]/10 text-[#f6465d] hover:bg-[#f6465d]/20']">
        删除
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  instance: {
    type: Object,
    required: true
  }
})

defineEmits(['switch', 'refresh', 'control', 'edit', 'delete'])

function getStatusClass(status) {
  const classes = {
    running: 'text-[#0ecb81]',
    stopped: 'text-text-tertiary',
    error: 'text-[#f6465d]',
    starting: 'text-[#f0b90b]',
    stopping: 'text-[#f0b90b]'
  }
  return classes[status] || 'text-text-tertiary'
}

function getStatusText(status) {
  const texts = {
    running: '运行中',
    stopped: '已停止',
    error: '错误',
    starting: '启动中',
    stopping: '停止中'
  }
  return texts[status] || '未知'
}
</script>
