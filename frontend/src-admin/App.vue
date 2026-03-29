<template>
  <div class="min-h-screen bg-dark-200 text-text-primary">
    <AdminNavbar v-if="isAuthenticated" />
    <div :class="isAuthenticated ? 'pt-0' : ''">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth.js'
import AdminNavbar from '@/components/AdminNavbar.vue'

const authStore = useAuthStore()
const isAuthenticated = computed(() => authStore.isAuthenticated)
</script>
