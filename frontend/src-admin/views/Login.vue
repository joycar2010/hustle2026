<template>
  <div class="min-h-screen bg-dark-200 flex items-center justify-center px-4">
    <div class="w-full max-w-md">
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="inline-flex w-16 h-16 bg-gradient-to-br from-red-600 to-red-800 rounded-2xl items-center justify-center shadow-lg mb-4">
          <span class="text-white font-bold text-3xl">管</span>
        </div>
        <h1 class="text-2xl font-bold text-text-primary">HustleXAU 总控管理</h1>
        <p class="text-sm text-text-tertiary mt-1">仅限 系统管理员 / 安全管理员 / 超级管理员 登录</p>
      </div>

      <!-- Error Banner -->
      <div v-if="permissionError" class="mb-4 p-3 bg-red-900/30 border border-red-700 rounded-lg text-sm text-red-300 text-center">
        ⚠️ 权限不足，您的账户角色无法访问总控管理平台
      </div>
      <div v-if="loginError" class="mb-4 p-3 bg-red-900/30 border border-red-700 rounded-lg text-sm text-red-300 text-center">
        {{ loginError }}
      </div>

      <!-- Login Form -->
      <div class="bg-dark-100 rounded-2xl p-8 border border-border-primary shadow-xl">
        <form @submit.prevent="handleLogin" class="space-y-5">
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">用户名</label>
            <input
              v-model="form.username"
              type="text"
              autocomplete="username"
              placeholder="请输入管理员用户名"
              class="w-full px-4 py-3 bg-dark-200 border border-border-primary rounded-lg focus:outline-none focus:border-red-500 text-text-primary transition-colors"
              :disabled="loading"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-text-secondary mb-2">密码</label>
            <div class="relative">
              <input
                v-model="form.password"
                :type="showPwd ? 'text' : 'password'"
                autocomplete="current-password"
                placeholder="请输入密码"
                class="w-full px-4 py-3 bg-dark-200 border border-border-primary rounded-lg focus:outline-none focus:border-red-500 text-text-primary transition-colors pr-12"
                :disabled="loading"
              />
              <button type="button" @click="showPwd = !showPwd" class="absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-secondary">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path v-if="!showPwd" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
                  <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
                </svg>
              </button>
            </div>
          </div>

          <button
            type="submit"
            :disabled="loading || !form.username || !form.password"
            class="w-full py-3 bg-red-700 hover:bg-red-600 disabled:bg-dark-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            <svg v-if="loading" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            <span>{{ loading ? '验证中...' : '登录管理平台' }}</span>
          </button>
        </form>

        <div class="mt-6 text-center">
          <a href="https://go.hustle2026.xyz" class="text-sm text-text-tertiary hover:text-primary transition-colors">
            → 返回交易操作面板
          </a>
        </div>
      </div>

      <p class="text-center text-xs text-text-tertiary mt-6">
        HustleXAU Admin v2.0.0 · 仅限授权人员访问
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const form = ref({ username: '', password: '' })
const loading = ref(false)
const loginError = ref('')
const showPwd = ref(false)
const permissionError = ref(route.query.error === 'permission')

async function handleLogin() {
  loginError.value = ''
  loading.value = true
  try {
    const ok = await authStore.login(form.value.username, form.value.password)
    if (ok) {
const ADMIN_ROLES = ['超级管理员', '系统管理员', '安全管理员', '管理员', 'admin', 'super_admin']
      if (!authStore.userRole) {
        // fetchUser 完全失败（网络/接口异常）
        authStore.logout()
        loginError.value = '获取用户信息失败，请稍后重试或联系管理员'
        return
      }
      if (!ADMIN_ROLES.includes(authStore.userRole)) {
        authStore.logout()
        loginError.value = `权限不足：账户角色「${authStore.userRole}」无法访问管理平台（需要：系统管理员 / 安全管理员 / 超级管理员）`
        return
      }
      router.push('/')
    } else {
      loginError.value = '用户名或密码错误'
    }
  } catch {
    loginError.value = '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>
