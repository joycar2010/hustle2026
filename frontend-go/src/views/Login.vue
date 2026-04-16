<template>
  <div class="min-h-screen flex items-center justify-center px-4">
    <div class="card max-w-md w-full">
      <div class="text-center mb-8">
        <div class="w-16 h-16 bg-primary rounded-full flex items-center justify-center mx-auto mb-4">
          <span class="text-dark-300 font-bold text-3xl">H</span>
        </div>
        <h1 class="text-3xl font-bold">Hustle XAU</h1>
        <p class="text-gray-400 mt-2">Arbitrage Trading System</p>
      </div>

      <form @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="block text-sm font-medium mb-2">Username</label>
          <input
            v-model="username"
            type="text"
            class="input-field"
            placeholder="Enter username"
            required
          />
        </div>

        <div>
          <label class="block text-sm font-medium mb-2">Password</label>
          <input
            v-model="password"
            type="password"
            class="input-field"
            placeholder="Enter password"
            required
          />
        </div>

        <div v-if="error" class="text-red-500 text-sm">
          {{ error }}
        </div>

        <button type="submit" class="btn-primary w-full" :disabled="loading">
          {{ loading ? 'Logging in...' : 'Login' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function handleLogin() {
  error.value = ''
  loading.value = true

  try {
    const success = await authStore.login(username.value, password.value)
    if (success) {
      router.push('/')
    } else {
      error.value = 'Invalid username or password'
    }
  } catch (err) {
    error.value = 'Login failed. Please try again.'
  } finally {
    loading.value = false
  }
}
</script>
