<template>
  <div class="card">
    <h2 class="text-xl font-bold mb-4">提醒声音设置</h2>
    <p class="text-sm text-text-secondary mb-4">
      管理系统提醒声音文件，上传的声音文件将自动同步到飞书云文档
    </p>

    <!-- 声音文件列表 -->
    <div class="mb-4">
      <div class="flex justify-between items-center mb-3">
        <h3 class="text-lg font-semibold">声音文件列表</h3>
        <div class="flex gap-2">
          <button
            @click="loadSounds"
            class="btn-secondary"
            :disabled="loading"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button
            @click="syncToFeishu"
            class="btn-primary"
            :disabled="syncing || sounds.length === 0"
          >
            <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            {{ syncing ? '同步中...' : '同步到飞书' }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="text-center py-8 text-text-secondary">
        加载中...
      </div>

      <div v-else-if="sounds.length === 0" class="text-center py-8 text-text-secondary">
        暂无声音文件，请上传
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="sound in sounds"
          :key="sound.filename"
          class="flex items-center justify-between p-3 bg-dark-200 rounded hover:bg-dark-100 transition-colors"
        >
          <div class="flex items-center gap-3 flex-1">
            <svg class="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <div class="flex-1">
              <div class="font-medium">{{ sound.filename }}</div>
              <div class="text-xs text-text-secondary">{{ formatFileSize(sound.size) }}</div>
            </div>
          </div>
          <div class="flex gap-2">
            <button
              @click="playSound(sound.filename)"
              class="p-2 hover:bg-dark-300 rounded transition-colors"
              title="试听"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button
              @click="deleteSound(sound.filename)"
              class="p-2 hover:bg-red-500/20 text-red-400 rounded transition-colors"
              title="删除"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 上传新文件 -->
    <div class="border-t border-border-primary pt-4">
      <h3 class="text-lg font-semibold mb-3">上传新声音文件</h3>
      <div class="flex gap-3">
        <input
          type="file"
          ref="fileInput"
          accept=".mp3,.wav,.ogg,.opus"
          @change="handleFileUpload"
          class="hidden"
        />
        <button
          @click="$refs.fileInput.click()"
          class="btn-primary flex-1"
          :disabled="uploading"
        >
          <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          {{ uploading ? '上传中...' : '选择文件上传' }}
        </button>
      </div>
      <p class="text-xs text-text-secondary mt-2">
        支持 MP3, WAV, OGG, OPUS 格式，文件将自动同步到飞书云文档
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'

const sounds = ref([])
const loading = ref(false)
const uploading = ref(false)
const syncing = ref(false)
const fileInput = ref(null)
const currentAudio = ref(null)

onMounted(() => {
  loadSounds()
})

async function loadSounds() {
  loading.value = true
  try {
    const response = await api.get('/api/v1/sounds')
    sounds.value = response.data.sounds || []
  } catch (error) {
    console.error('加载声音文件失败:', error)
    alert(error.response?.data?.detail || '加载声音文件失败')
  } finally {
    loading.value = false
  }
}

async function handleFileUpload(event) {
  const file = event.target.files[0]
  if (!file) return

  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await api.post('/api/v1/sounds/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })

    if (response.data.success) {
      alert(`文件上传成功！\n${response.data.message}`)
      await loadSounds()
      event.target.value = ''
    }
  } catch (error) {
    console.error('上传失败:', error)
    alert(error.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function syncToFeishu() {
  if (!confirm('确定要将所有声音文件同步到飞书云文档吗？')) {
    return
  }

  syncing.value = true
  try {
    const response = await api.post('/api/v1/sounds/sync-to-feishu')
    if (response.data.success) {
      const results = response.data.results || []
      const successCount = results.filter(r => r.success).length
      const failedCount = results.length - successCount

      let message = `同步完成！\n成功: ${successCount} 个文件`
      if (failedCount > 0) {
        message += `\n失败: ${failedCount} 个文件`
      }
      alert(message)
    }
  } catch (error) {
    console.error('同步失败:', error)
    alert(error.response?.data?.detail || '同步失败')
  } finally {
    syncing.value = false
  }
}

function playSound(filename) {
  if (currentAudio.value) {
    currentAudio.value.pause()
    currentAudio.value = null
  }

  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://13.115.21.77:8000'
  const soundUrl = `${apiBaseUrl}/sounds/${filename}`

  currentAudio.value = new Audio(soundUrl)
  currentAudio.value.play().catch(error => {
    console.error('播放失败:', error)
    alert('播放失败')
  })
}

async function deleteSound(filename) {
  if (!confirm(`确定要删除声音文件 "${filename}" 吗？`)) {
    return
  }

  try {
    await api.delete(`/api/v1/sounds/${filename}`)
    alert('删除成功')
    await loadSounds()
  } catch (error) {
    console.error('删除失败:', error)
    alert(error.response?.data?.detail || '删除失败')
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>
