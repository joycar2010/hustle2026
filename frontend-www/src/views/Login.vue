<template>
  <div class="min-h-screen bg-dark-200 flex flex-col items-center justify-center px-4 py-8">
    <div class="w-full max-w-sm">
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="inline-flex w-14 h-14 bg-gradient-to-br from-primary to-primary-hover rounded-2xl items-center justify-center shadow-lg mb-3">
          <span class="text-dark-300 font-bold text-2xl">H</span>
        </div>
        <h1 class="text-xl font-bold">HustleXAU</h1>
        <p class="text-sm text-text-tertiary mt-1">实时收益查看平台</p>
      </div>

      <div v-if="errMsg" class="mb-4 p-3 bg-red-900/30 border border-red-700 rounded-xl text-sm text-red-300 text-center">{{ errMsg }}</div>

      <div class="bg-dark-100 rounded-2xl p-6 border border-border-primary shadow-xl">
        <form @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-1.5">用户名</label>
            <input v-model="form.username" type="text" autocomplete="username" placeholder="请输入用户名"
              class="w-full px-4 py-3 bg-dark-200 border border-border-primary rounded-xl focus:outline-none focus:border-primary text-text-primary transition-colors text-base"
              :disabled="loading" />
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-1.5">密码</label>
            <div class="relative">
              <input v-model="form.password" :type="showPwd ? 'text' : 'password'" autocomplete="current-password" placeholder="请输入密码"
                class="w-full px-4 py-3 bg-dark-200 border border-border-primary rounded-xl focus:outline-none focus:border-primary text-text-primary transition-colors text-base pr-12"
                :disabled="loading" />
              <button type="button" @click="showPwd = !showPwd" class="absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary p-1">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path v-if="!showPwd" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
                  <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
                </svg>
              </button>
            </div>
          </div>
          <button type="submit" :disabled="loading || !form.username || !form.password"
            class="w-full py-3.5 bg-primary hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed text-dark-300 font-bold rounded-xl transition-colors flex items-center justify-center gap-2 text-base mt-2">
            <svg v-if="loading" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            {{ loading ? '登录中...' : '登录' }}
          </button>
        </form>
      </div>

      <div class="mt-6 text-center space-y-2">
        <a href="https://go.hustle2026.xyz" class="block text-sm text-text-tertiary hover:text-primary transition-colors">→ 交易操作面板</a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const auth = useAuthStore()
const form = ref({ username: '', password: '' })
const loading = ref(false)
const errMsg = ref('')
const showPwd = ref(false)

async function handleLogin() {
  errMsg.value = ''
  loading.value = true
  try {
    const ok = await auth.login(form.value.username, form.value.password)
    if (ok) router.push('/')
    else errMsg.value = '用户名或密码错误'
  } catch { errMsg.value = '登录失败，请稍后重试' }
  finally { loading.value = false }
}
</script>
