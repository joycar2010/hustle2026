<template>
  <div id="app" class="min-h-screen">
    <LoadingSpinner />
    <Navbar v-if="isAuthenticated" />
    <router-view />
    <NotificationPopup v-if="isAuthenticated" />
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAlertMonitoring } from '@/composables/useAlertMonitoring'
import Navbar from '@/components/Navbar.vue'
import NotificationPopup from '@/components/NotificationPopup.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'

const authStore = useAuthStore()
const isAuthenticated = computed(() => authStore.isAuthenticated)

// Initialize alert monitoring when authenticated
if (isAuthenticated.value) {
  useAlertMonitoring()
}

// 通知加载完成
onMounted(() => {
  setTimeout(() => {
    window.dispatchEvent(new Event('app-loaded'))
  }, 500)
})
</script>
