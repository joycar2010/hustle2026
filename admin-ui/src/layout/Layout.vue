<template>
  <el-container>
    <el-aside width="180px">
      <div class="brand">⚡ DexCexMix</div>
      <el-menu :default-active="$route.path" router>
        <el-menu-item index="/overview">总览</el-menu-item>
        <el-menu-item index="/engine">引擎控制</el-menu-item>
        <el-menu-item index="/routes">路由</el-menu-item>
        <el-menu-item index="/alerts">告警历史</el-menu-item>
        <el-menu-item index="/audit">操作审计</el-menu-item>
        <el-menu-item index="/lending">借贷增强</el-menu-item>
        <el-menu-item index="/coin">coin 借币</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header>
        <b>{{ $route.meta.title || '' }}</b>
        <span class="dim" style="font-size:12px">{{ now }}</span>
        <span class="dim" style="font-size:12px">{{ auth.name }} <el-tag size="small" v-if="auth.role">{{ auth.role }}</el-tag></span>
        <el-button size="small" style="margin-left:auto" @click="logout">退出</el-button>
      </el-header>
      <el-main><router-view /></el-main>
    </el-container>
  </el-container>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../store/auth'
import { api } from '../api'
const auth = useAuth(); const router = useRouter(); const now = ref(''); let t
onMounted(async () => {
  t = setInterval(() => (now.value = new Date().toLocaleTimeString()), 1000)
  try { const d = await api.config(); auth.setMe(d.me) } catch (e) {}
})
onUnmounted(() => clearInterval(t))
function logout() { auth.logout(); router.push('/login') }
</script>
