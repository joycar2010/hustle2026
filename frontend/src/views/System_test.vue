<template>
  <div class="container mx-auto px-4 py-6">
    <h1 class="text-3xl font-bold mb-6">系统管理</h1>
  </div>
</template>

<script setup>
import { ref } from 'vue'
const activeTab = ref('users')
</script>

<style scoped>
.card {
  background: #1a1d21;
}
</style>
