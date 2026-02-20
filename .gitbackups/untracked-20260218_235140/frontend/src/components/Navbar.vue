<template>
  <nav class="bg-dark-100 border-b border-gray-800">
    <div class="container mx-auto px-4">
      <div class="flex items-center justify-between h-16">
        <!-- Logo -->
        <div class="flex items-center space-x-8">
          <router-link to="/" class="flex items-center space-x-2">
            <div class="w-8 h-8 bg-primary rounded-full flex items-center justify-center">
              <span class="text-dark-300 font-bold text-lg">H</span>
            </div>
            <span class="text-xl font-bold hidden md:block">Hustle XAU</span>
          </router-link>

          <!-- Desktop Navigation -->
          <div class="hidden md:flex space-x-6">
            <router-link to="/" class="nav-link">Dashboard</router-link>
            <router-link to="/trading" class="nav-link">Trading</router-link>
            <router-link to="/strategies" class="nav-link">Strategies</router-link>
            <router-link to="/positions" class="nav-link">Positions</router-link>
            <router-link to="/accounts" class="nav-link">Accounts</router-link>
            <router-link to="/risk" class="nav-link">Risk</router-link>
          </div>
        </div>

        <!-- Right Side -->
        <div class="flex items-center space-x-4">
          <!-- User Info -->
          <div class="hidden md:flex items-center space-x-2">
            <div class="text-right">
              <div class="text-sm font-medium">{{ user?.username }}</div>
              <div class="text-xs text-gray-400">{{ user?.email }}</div>
            </div>
          </div>

          <!-- Logout Button -->
          <button @click="handleLogout" class="btn-primary text-sm">
            Logout
          </button>

          <!-- Mobile Menu Button -->
          <button @click="mobileMenuOpen = !mobileMenuOpen" class="md:hidden">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Mobile Menu -->
      <div v-if="mobileMenuOpen" class="md:hidden py-4 space-y-2">
        <router-link to="/" class="block py-2 px-4 hover:bg-dark-200 rounded">Dashboard</router-link>
        <router-link to="/trading" class="block py-2 px-4 hover:bg-dark-200 rounded">Trading</router-link>
        <router-link to="/strategies" class="block py-2 px-4 hover:bg-dark-200 rounded">Strategies</router-link>
        <router-link to="/positions" class="block py-2 px-4 hover:bg-dark-200 rounded">Positions</router-link>
        <router-link to="/accounts" class="block py-2 px-4 hover:bg-dark-200 rounded">Accounts</router-link>
        <router-link to="/risk" class="block py-2 px-4 hover:bg-dark-200 rounded">Risk</router-link>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const mobileMenuOpen = ref(false)

const user = computed(() => authStore.user)

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.nav-link {
  @apply text-gray-300 hover:text-white transition;
}

.router-link-active {
  @apply text-primary;
}
</style>
