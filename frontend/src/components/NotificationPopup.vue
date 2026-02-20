<template>
  <Transition name="slide-up">
    <div
      v-if="notificationStore.activePopup"
      class="fixed bottom-6 right-6 z-50 w-96 bg-[#1e2329] border border-[#2b3139] rounded-lg shadow-2xl overflow-hidden"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-[#2b3139]">
        <div class="flex items-center space-x-2">
          <div :class="['w-2 h-2 rounded-full animate-pulse', getStatusColor(notificationStore.activePopup.level)]"></div>
          <h3 class="text-sm font-bold">通知</h3>
        </div>
        <button
          @click="notificationStore.dismissPopup()"
          class="text-gray-400 hover:text-white transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Content -->
      <div class="p-4">
        <div class="flex items-start space-x-3">
          <!-- Icon -->
          <div :class="['flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center', getIconBgColor(notificationStore.activePopup.level)]">
            <svg v-if="notificationStore.activePopup.level === 'critical'" class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <svg v-else-if="notificationStore.activePopup.level === 'warning'" class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
            <svg v-else class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>

          <!-- Message -->
          <div class="flex-1 min-w-0">
            <h4 :class="['font-bold text-sm mb-1', getTitleColor(notificationStore.activePopup.level)]">
              {{ notificationStore.activePopup.title }}
            </h4>
            <p class="text-sm text-gray-300 leading-relaxed">
              {{ notificationStore.activePopup.message }}
            </p>
            <p class="text-xs text-gray-500 mt-2">
              {{ formatTime(notificationStore.activePopup.timestamp) }}
            </p>
          </div>
        </div>
      </div>

      <!-- Audio indicator -->
      <div v-if="notificationStore.isAudioPlaying" class="px-4 py-2 bg-[#252930] border-t border-[#2b3139]">
        <div class="flex items-center space-x-2">
          <div class="flex space-x-1">
            <div v-for="i in 3" :key="i" class="w-1 h-3 bg-primary rounded-sm animate-pulse" :style="{ animationDelay: `${i * 0.15}s` }"></div>
          </div>
          <span class="text-xs text-gray-400">播放提示音...</span>
        </div>
      </div>

      <!-- Progress bar -->
      <div class="h-1 bg-[#2b3139]">
        <div class="h-full bg-primary animate-progress"></div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { useNotificationStore } from '@/stores/notification'
import dayjs from 'dayjs'

const notificationStore = useNotificationStore()

function getStatusColor(level) {
  const colors = {
    critical: 'bg-[#f6465d]',
    warning: 'bg-[#ff9800]',
    info: 'bg-[#0ecb81]'
  }
  return colors[level] || 'bg-gray-400'
}

function getIconBgColor(level) {
  const colors = {
    critical: 'bg-[#f6465d]',
    warning: 'bg-[#ff9800]',
    info: 'bg-[#0ecb81]'
  }
  return colors[level] || 'bg-gray-600'
}

function getTitleColor(level) {
  const colors = {
    critical: 'text-[#f6465d]',
    warning: 'text-[#ff9800]',
    info: 'text-[#0ecb81]'
  }
  return colors[level] || 'text-white'
}

function formatTime(timestamp) {
  return dayjs(timestamp).format('MM-DD HH:mm:ss')
}
</script>

<style scoped>
.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.3s ease;
}

.slide-up-enter-from {
  transform: translateY(100%);
  opacity: 0;
}

.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

@keyframes progress {
  0% {
    width: 0%;
  }
  100% {
    width: 100%;
  }
}

.animate-progress {
  animation: progress 10s linear;
}
</style>
