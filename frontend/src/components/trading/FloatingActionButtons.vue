<template>
  <div class="floating-buttons-container">
    <!-- Account Status Button -->
    <button
      @click="toggleAccountStatus"
      class="floating-btn account-btn"
      :class="{ 'active': showAccountStatus }"
    >
      <span class="btn-icon">💰</span>
      <span class="btn-label">账户</span>
    </button>

    <!-- Risk Management Button -->
    <button
      @click="toggleRisk"
      class="floating-btn risk-btn"
      :class="{ 'active': showRisk }"
    >
      <span class="btn-icon">⚠️</span>
      <span class="btn-label">风险</span>
    </button>

    <!-- Account Status Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showAccountStatus" class="modal-overlay" @click="closeAccountStatus">
          <div class="modal-content" @click.stop>
            <div class="modal-header">
              <h3 class="modal-title">账户状态</h3>
              <button @click="closeAccountStatus" class="close-btn">×</button>
            </div>
            <div class="modal-body">
              <AccountStatusPanel />
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Risk Management Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showRisk" class="modal-overlay" @click="closeRisk">
          <div class="modal-content" @click.stop>
            <div class="modal-header">
              <h3 class="modal-title">风险管理</h3>
              <button @click="closeRisk" class="close-btn">×</button>
            </div>
            <div class="modal-body">
              <Risk />
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import AccountStatusPanel from '@/components/trading/AccountStatusPanel.vue'
import Risk from '@/views/Risk.vue'

const showAccountStatus = ref(false)
const showRisk = ref(false)

function toggleAccountStatus() {
  showAccountStatus.value = !showAccountStatus.value
  if (showAccountStatus.value) {
    showRisk.value = false
  }
}

function toggleRisk() {
  showRisk.value = !showRisk.value
  if (showRisk.value) {
    showAccountStatus.value = false
  }
}

function closeAccountStatus() {
  showAccountStatus.value = false
}

function closeRisk() {
  showRisk.value = false
}
</script>

<style scoped>
.floating-buttons-container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  z-index: 1000;
}

.floating-btn {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #ffffff;
  font-size: 12px;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  transition: all 0.3s;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 44px; /* 移动端最小点击区域 */
  min-height: 44px;
}

.floating-btn:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
}

.floating-btn:active {
  transform: scale(0.95);
}

.floating-btn.active {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
}

.account-btn {
  background: linear-gradient(135deg, #0ecb81 0%, #0db774 100%);
}

.risk-btn {
  background: linear-gradient(135deg, #f6465d 0%, #e03d52 100%);
}

.btn-icon {
  font-size: 20px;
}

.btn-label {
  font-size: 10px;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 16px;
}

.modal-content {
  background-color: #1e2329;
  border-radius: 12px;
  width: 100%;
  max-width: 500px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #2b3139;
  flex-shrink: 0;
}

.modal-title {
  font-size: 16px;
  font-weight: bold;
  color: #ffffff;
  margin: 0;
}

.close-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background-color: #252930;
  color: #ffffff;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background-color: #2b3139;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 0;
}

/* Modal Transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-content,
.modal-leave-active .modal-content {
  transition: transform 0.3s;
}

.modal-enter-from .modal-content,
.modal-leave-to .modal-content {
  transform: scale(0.9);
}

/* 仅在移动端显示浮动按钮 */
@media (min-width: 1024px) {
  .floating-buttons-container {
    display: none;
  }
}

/* 移动端优化 */
@media (orientation: portrait), (max-width: 750px) {
  .floating-buttons-container {
    bottom: 16px;
    right: 16px;
  }

  .floating-btn {
    width: 56px;
    height: 56px;
  }

  .modal-content {
    max-height: 90vh;
    border-radius: 12px 12px 0 0;
  }

  .modal-overlay {
    padding: 0;
    align-items: flex-end;
  }
}
</style>
