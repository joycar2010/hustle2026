<template>
  <div class="login-wrap"><div class="card" style="width:340px">
    <h3>DexCexMix 控制台</h3>
    <el-input v-model="t" placeholder="操作令牌 X-Op-Token" show-password @keyup.enter="login" />
    <el-button type="primary" style="width:100%;margin-top:12px" @click="login">登录</el-button>
    <div class="dim" style="margin-top:8px;font-size:11px">只读可用 dashboard token;操作/管理需 operator 令牌</div>
  </div></div>
</template>
<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../store/auth'
const t = ref(''); const router = useRouter(); const auth = useAuth()
function login() { if (!t.value) return; auth.login(t.value); router.push('/overview') }
</script>
