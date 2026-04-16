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
            <h3 class="text-xl font-bold">修改密码</h3>
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
            <!-- Current Password -->
            <div>
              <label class="block text-sm font-medium mb-2">当前密码</label>
              <input
                v-model="formData.currentPassword"
                type="password"
                required
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入当前密码"
              />
            </div>

            <!-- New Password -->
            <div>
              <label class="block text-sm font-medium mb-2">新密码</label>
              <input
                v-model="formData.newPassword"
                type="password"
                required
                minlength="6"
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入新密码（至少6位）"
              />
              <p class="text-xs text-text-tertiary mt-1">密码长度至少为6个字符</p>
            </div>

            <!-- Confirm New Password -->
            <div>
              <label class="block text-sm font-medium mb-2">确认新密码</label>
              <input
                v-model="formData.confirmPassword"
                type="password"
                required
                minlength="6"
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="再次输入新密码"
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
              {{ loading ? '修改中...' : '确认修改' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import api from '@/services/api'

const props = defineProps({
  isOpen: {
    type: Boolean,
    required: true
  }
})

const emit = defineEmits(['close', 'updated'])

const loading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const formData = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

// Watch for modal open to reset form
watch(() => props.isOpen, (newValue) => {
  if (newValue) {
    formData.value = {
      currentPassword: '',
      newPassword: '',
      confirmPassword: ''
    }
    errorMessage.value = ''
    successMessage.value = ''
  }
})

async function handleSubmit() {
  // Validate passwords match
  if (formData.value.newPassword !== formData.value.confirmPassword) {
    errorMessage.value = '新密码和确认密码不一致'
    return
  }

  // Validate password length
  if (formData.value.newPassword.length < 6) {
    errorMessage.value = '新密码长度至少为6个字符'
    return
  }

  loading.value = true
  errorMessage.value = ''
  successMessage.value = ''

  try {
    await api.put('/api/v1/users/password', {
      current_password: formData.value.currentPassword,
      new_password: formData.value.newPassword
    })

    successMessage.value = '密码修改成功！'

    // Close modal after 1.5 seconds
    setTimeout(() => {
      emit('updated')
      closeModal()
    }, 1500)
  } catch (error) {
    console.error('Failed to change password:', error)
    errorMessage.value = error.response?.data?.detail || '密码修改失败，请检查当前密码是否正确'
  } finally {
    loading.value = false
  }
}

function closeModal() {
  emit('close')
}
</script>
