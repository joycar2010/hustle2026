<template>
  <div class="min-h-screen flex items-center justify-center">
    <div class="bg-dark-100 p-8 rounded-xl border border-border-primary w-96">
      <div class="text-center mb-6">
        <div class="text-2xl font-bold">OpenCLAW</div>
        <div class="text-xs text-text-tertiary mt-1">智能体控制台 · 操作员登录</div>
      </div>
      <form @submit.prevent="login" class="space-y-3">
        <input v-model="username" placeholder="账号" class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none"/>
        <input v-model="password" type="password" placeholder="密码" class="w-full bg-dark-200 border border-border-primary rounded px-3 py-2 text-sm focus:border-primary outline-none"/>
        <button class="w-full bg-primary text-dark-300 font-semibold py-2 rounded hover:bg-primary-hover">登录</button>
        <div v-if="err" class="text-danger text-xs text-center">{{ err }}</div>
      </form>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api'
const username = ref(''), password = ref(''), err = ref('')
const router = useRouter()
async function login() {
  err.value = ''
  try {
    const r = await api.post('/api/v1/auth/login', { username: username.value, password: password.value })
    const token = r.data?.access_token || r.data?.token
    if (!token) throw new Error('no token')
    localStorage.setItem('access_token', token)
    router.push('/dashboard')
  } catch (e) { err.value = e.response?.data?.detail || '登录失败' }
}
</script>
