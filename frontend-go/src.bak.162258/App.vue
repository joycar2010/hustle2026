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

// Verify token validity on app mount
onMounted(async () => {
  // If user has a token, verify it's valid
  if (authStore.isAuthenticated) {
    try {
      await authStore.fetchUser()
    } catch (error) {
      // Token is invalid, clear it
      authStore.logout()
    }
  }

  // Notify app loaded
  setTimeout(() => {
    window.dispatchEvent(new Event('app-loaded'))
  }, 500)
})
</script>
