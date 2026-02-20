<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 overflow-y-auto">
    <div class="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div class="fixed inset-0 transition-opacity bg-gray-900 bg-opacity-75" @click="closeModal"></div>

      <!-- Modal panel -->
      <div class="inline-block align-bottom bg-dark-100 rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full border border-border-primary">
        <!-- Header -->
        <div class="bg-dark-200 px-6 py-4 border-b border-border-primary">
          <div class="flex items-center justify-between">
            <h3 class="text-xl font-bold">编辑个人信息</h3>
            <button @click="closeModal" class="text-text-tertiary hover:text-text-primary transition-colors">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Body -->
        <form @submit.prevent="handleSubmit" class="px-6 py-4">
          <div class="space-y-4">
            <!-- Username -->
            <div>
              <label class="block text-sm font-medium mb-2">用户名</label>
              <input
                v-model="formData.username"
                type="text"
                required
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入用户名"
              />
            </div>

            <!-- Email -->
            <div>
              <label class="block text-sm font-medium mb-2">邮箱</label>
              <input
                v-model="formData.email"
                type="email"
                required
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入邮箱地址"
              />
            </div>

            <!-- Phone (optional) -->
            <div>
              <label class="block text-sm font-medium mb-2">手机号码 (可选)</label>
              <input
                v-model="formData.phone"
                type="tel"
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入手机号码"
              />
            </div>

            <!-- Error message -->
            <div v-if="errorMessage" class="bg-danger/10 border border-danger rounded p-3">
              <p class="text-sm text-danger">{{ errorMessage }}</p>
            </div>

            <!-- Success message -->
            <div v-if="successMessage" class="bg-success/10 border border-success rounded p-3">
              <p class="text-sm text-success">{{ successMessage }}</p>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex justify-end space-x-3 mt-6 pt-4 border-t border-border-secondary">
            <button
              type="button"
              @click="closeModal"
              class="px-4 py-2 bg-dark-200 hover:bg-dark-50 rounded transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              :disabled="loading"
              class="px-4 py-2 bg-primary hover:bg-primary-dark rounded font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {{ loading ? '保存中...' : '保存' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/services/api'

const props = defineProps({
  isOpen: {
    type: Boolean,
    required: true
  }
})

const emit = defineEmits(['close', 'updated'])

const authStore = useAuthStore()
const loading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const formData = ref({
  username: '',
  email: '',
  phone: ''
})

// Watch for modal open to populate form with current user data
watch(() => props.isOpen, (newValue) => {
  if (newValue && authStore.user) {
    formData.value = {
      username: authStore.user.username || '',
      email: authStore.user.email || '',
      phone: authStore.user.phone || ''
    }
    errorMessage.value = ''
    successMessage.value = ''
  }
})

async function handleSubmit() {
  loading.value = true
  errorMessage.value = ''
  successMessage.value = ''

  try {
    const response = await api.put('/api/v1/users/profile', formData.value)

    // Update auth store with new user data
    authStore.updateUser(response.data)

    successMessage.value = '个人信息更新成功！'

    // Close modal after 1.5 seconds
    setTimeout(() => {
      emit('updated')
      closeModal()
    }, 1500)
  } catch (error) {
    console.error('Failed to update profile:', error)
    errorMessage.value = error.response?.data?.detail || '更新失败，请重试'
  } finally {
    loading.value = false
  }
}

function closeModal() {
  emit('close')
}
</script>
