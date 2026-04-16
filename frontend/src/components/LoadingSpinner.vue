<template>
  <transition name="fade">
    <div v-if="isLoading" class="loading-overlay">
      <div class="loading-container">
        <div class="spinner"></div>
        <div class="loading-text">加载中...</div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const isLoading = ref(true)

onMounted(() => {
  // 监听应用加载完成事件
  window.addEventListener('app-loaded', () => {
    setTimeout(() => {
      isLoading.value = false
    }, 200) // 从300ms减少到200ms
  })

  // 最多显示3秒，防止卡住（从5秒减少到3秒）
  setTimeout(() => {
    isLoading.value = false
  }, 3000)
})
</script>

<style scoped>
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #1a1d21;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

.spinner {
  width: 50px;
  height: 50px;
  border: 4px solid rgba(240, 185, 11, 0.1);
  border-top-color: #f0b90b;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-text {
  color: #f0b90b;
  font-size: 1rem;
  font-weight: 500;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 移动端优化 (包括2K屏幕) */
@media (orientation: portrait) and (max-width: 1500px), (max-width: 767px) {
  .spinner {
    width: 60px; /* 从40px增加到60px */
    height: 60px;
    border-width: 4px; /* 从3px增加到4px */
  }

  .loading-text {
    font-size: 1.125rem; /* 从0.875rem增加到1.125rem */
  }
}

/* 2K屏幕特别优化 */
@media (orientation: portrait) and (max-width: 1500px) and (min-resolution: 2dppx),
       (orientation: portrait) and (max-width: 1500px) and (-webkit-min-device-pixel-ratio: 2) {
  .spinner {
    width: 70px; /* 2K屏幕使用更大的spinner */
    height: 70px;
    border-width: 5px;
  }

  .loading-text {
    font-size: 1.25rem; /* 2K屏幕使用更大的字体 */
    font-weight: 600;
  }
}
</style>
