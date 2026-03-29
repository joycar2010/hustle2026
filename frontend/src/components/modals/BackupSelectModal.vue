<template>
  <div v-if="show" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click.self="close">
    <div class="bg-dark-200 rounded-lg p-6 w-full max-w-3xl">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-xl font-bold">选择备份文件</h3>
        <button @click="close" class="text-gray-400 hover:text-white">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div v-if="backups.length === 0" class="text-center py-8 text-gray-400">
        暂无备份文件
      </div>

      <div v-else class="space-y-2 max-h-96 overflow-y-auto">
        <div
          v-for="backup in backups"
          :key="backup.filename"
          class="bg-dark-100 rounded p-4 hover:bg-dark-50 cursor-pointer transition-colors"
          @click="selectBackup(backup)"
        >
          <div class="flex justify-between items-center">
            <div>
              <div class="font-medium">{{ backup.filename }}</div>
              <div class="text-sm text-gray-400">创建时间: {{ backup.created_at }}</div>
            </div>
            <div class="text-sm text-gray-400">{{ backup.size }}</div>
          </div>
        </div>
      </div>

      <div class="flex justify-end space-x-3 mt-6">
        <button @click="close" class="btn-secondary">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import api from '@/services/api'

const props = defineProps({
  show: Boolean
})

const emit = defineEmits(['close', 'select'])

const backups = ref([])

watch(() => props.show, async (newVal) => {
  if (newVal) {
    await loadBackups()
  }
})

async function loadBackups() {
  try {
    const response = await api.get('/api/v1/system/database/backups')
    backups.value = response.data
  } catch (error) {
    console.error('Failed to load backups:', error)
    alert('加载备份列表失败: ' + (error.response?.data?.detail || error.message))
  }
}

function selectBackup(backup) {
  emit('select', backup.filename)
  close()
}

function close() {
  emit('close')
}
</script>

<style scoped>
.btn-secondary {
  @apply inline-flex items-center px-4 py-2 bg-dark-200 hover:bg-dark-100 text-text-primary rounded-lg transition-colors font-medium;
}
</style>
