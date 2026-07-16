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
              <label class="block text-sm font-medium mb-2">用户名 <span class="text-danger">*</span></label>
              <input
                v-model="formData.username"
                type="text"
                required
                disabled
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary opacity-60 cursor-not-allowed"
                placeholder="用户名不可修改"
              />
            </div>

            <!-- Email -->
            <div>
              <label class="block text-sm font-medium mb-2">邮箱 <span class="text-danger">*</span></label>
              <input
                v-model="formData.email"
                type="email"
                required
                class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                placeholder="输入邮箱地址"
              />
            </div>

            <!-- Feishu Fields -->
            <div class="border-t border-border-primary pt-4 mt-4">
              <h4 class="text-sm font-medium mb-3 text-text-secondary">飞书通知配置</h4>
              <div class="space-y-3">
                <div>
                  <label class="block text-sm font-medium mb-2">飞书 Open ID</label>
                  <input
                    v-model="formData.feishu_open_id"
                    type="text"
                    class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                    placeholder="ou_xxxxxxxxxxxxxxxx"
                  />
                  <p class="text-xs text-text-secondary mt-1">用于接收飞书通知，优先级最高</p>
                </div>
                <div>
                  <label class="block text-sm font-medium mb-2">飞书手机号</label>
                  <input
                    v-model="formData.feishu_mobile"
                    type="text"
                    class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                    placeholder="+8613800138000"
                  />
                  <p class="text-xs text-text-secondary mt-1">需包含国家代码，如 +86</p>
                </div>
                <div>
                  <label class="block text-sm font-medium mb-2">飞书 Union ID</label>
                  <input
                    v-model="formData.feishu_union_id"
                    type="text"
                    class="w-full px-3 py-2 bg-dark-100 border border-border-primary rounded focus:outline-none focus:border-primary"
                    placeholder="on_xxxxxxxxxxxxxxxx"
                  />
                  <p class="text-xs text-text-secondary mt-1">跨应用唯一标识（可选）</p>
                </div>
                <div class="flex items-center">
                  <input
                    v-model="formData.feishu_enabled"
                    type="checkbox"
                    id="profile-feishu-enabled"
                    class="mr-2"
                  />
                  <label for="profile-feishu-enabled" class="text-sm">启用飞书通知</label>
                </div>
              </div>
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
  feishu_open_id: '',
  feishu_mobile: '',
  feishu_union_id: '',
  feishu_enabled: false
})

// Watch for modal open to populate form with current user data
watch(() => props.isOpen, async (newValue) => {
  if (newValue) {
    // Fetch latest user data from API
    try {
      const response = await api.get('/api/v1/users/me')
      const userData = response.data

      formData.value = {
        username: userData.username || '',
        email: userData.email || '',
        feishu_open_id: userData.feishu_open_id || '',
        feishu_mobile: userData.feishu_mobile || '',
        feishu_union_id: userData.feishu_union_id || '',
        feishu_enabled: !!(userData.feishu_open_id || userData.feishu_mobile)
      }

      // Update auth store with latest data
      authStore.updateUser(userData)
    } catch (error) {
      console.error('Failed to fetch user data:', error)
      // Fallback to auth store data
      if (authStore.user) {
        formData.value = {
          username: authStore.user.username || '',
          email: authStore.user.email || '',
          feishu_open_id: authStore.user.feishu_open_id || '',
          feishu_mobile: authStore.user.feishu_mobile || '',
          feishu_union_id: authStore.user.feishu_union_id || '',
          feishu_enabled: !!(authStore.user.feishu_open_id || authStore.user.feishu_mobile)
        }
      }
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
    // Prepare data, convert empty strings to null
    const submitData = {
      username: formData.value.username,
      email: formData.value.email,
      feishu_open_id: formData.value.feishu_open_id || null,
      feishu_mobile: formData.value.feishu_mobile || null,
      feishu_union_id: formData.value.feishu_union_id || null
    }

    console.log('Updating profile with data:', submitData)
    const response = await api.put('/api/v1/users/me', submitData)
    console.log('Update response:', response.data)

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
    console.error('Error details:', error.response?.data)
    errorMessage.value = error.response?.data?.detail || '更新失败，请重试'
  } finally {
    loading.value = false
  }
}

function closeModal() {
  emit('close')
}
</script>
