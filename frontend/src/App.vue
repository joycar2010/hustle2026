<template>
  <div id="app" class="min-h-screen">
    <Navbar v-if="isAuthenticated" />
    <router-view />
    <NotificationPopup v-if="isAuthenticated" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAlertMonitoring } from '@/composables/useAlertMonitoring'
import Navbar from '@/components/Navbar.vue'
import NotificationPopup from '@/components/NotificationPopup.vue'

const authStore = useAuthStore()
const isAuthenticated = computed(() => authStore.isAuthenticated)

// Initialize alert monitoring when authenticated
if (isAuthenticated.value) {
  useAlertMonitoring()
}
</script>
