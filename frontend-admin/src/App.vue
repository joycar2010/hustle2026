<template>
  <div class="min-h-screen bg-dark-200 text-text-primary">
    <AdminNavbar v-if="showNavbar" />
    <div :class="isAuthenticated ? 'pt-0' : ''">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'
import AdminNavbar from '@/components/AdminNavbar.vue'

const authStore = useAuthStore()
const route = useRoute()
const isAuthenticated = computed(() => authStore.isAuthenticated)
const isDetached = computed(() => route.query.mode === 'detached')
const showNavbar = computed(() => isAuthenticated.value && !isDetached.value)
</script>
