<template>
  <div class="min-h-screen bg-dark-200 text-text-primary">
    <router-view />
    <MobileNavbar v-if="isAuthenticated && showNav" />
    <div v-if="isAuthenticated && showNav" class="h-16 md:h-12"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'
import MobileNavbar from '@/components/MobileNavbar.vue'

const authStore = useAuthStore()
const route = useRoute()
const isAuthenticated = computed(() => authStore.isAuthenticated)
const showNav = computed(() => route.path !== '/login')
</script>
