<template>
  <nav v-show="!navbarHidden" class="bg-dark-100 border-b border-border-primary sticky top-0 z-50">
    <div class="container mx-auto px-4">
      <div class="flex items-center justify-between h-16">
        <!-- Logo -->
        <div class="flex items-center space-x-6">
          <!-- Alert Switches -->
          <div class="hidden xl:flex items-center space-x-2 mr-8" :class="{ 'xl:hidden': navbarCollapsed }">
            <!-- Alert Sound Switch -->
            <div class="flex items-center space-x-2 px-3 py-2 bg-dark-200 rounded-lg">
              <svg class="w-4 h-4 text-text-secondary flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
              </svg>
              <span class="text-sm text-text-secondary whitespace-nowrap">提醒音</span>
              <button
                @click="toggleAlertSound"
                :class="[
                  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0 cursor-pointer hover:opacity-80',
                  notificationStore.alertSoundEnabled ? 'bg-primary' : 'bg-gray-600'
                ]"
              >
                <span
                  :class="[
                    'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                    notificationStore.alertSoundEnabled ? 'translate-x-5' : 'translate-x-1'
                  ]"
                />
              </button>
            </div>

            <!-- Single-Leg Alert Switch -->
            <div class="flex items-center space-x-2 px-3 py-2 bg-dark-200 rounded-lg">
              <svg class="w-4 h-4 text-text-secondary flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <span class="text-sm text-text-secondary whitespace-nowrap">单腿提醒</span>
              <button
                @click="toggleSingleLegAlert"
                :class="[
                  'relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0 cursor-pointer hover:opacity-80',
                  notificationStore.singleLegAlertEnabled ? 'bg-primary' : 'bg-gray-600'
                ]"
              >
                <span
                  :class="[
                    'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                    notificationStore.singleLegAlertEnabled ? 'translate-x-5' : 'translate-x-1'
                  ]"
                />
              </button>
            </div>
          </div>

          <router-link to="/" class="flex items-center space-x-3 flex-shrink-0">
            <div class="w-10 h-10 bg-gradient-to-br from-primary to-primary-hover rounded-lg flex items-center justify-center shadow-lg">
              <span class="text-dark-300 font-bold text-xl">H</span>
            </div>
            <div class="hidden md:block" :class="{ 'md:hidden': navbarCollapsed }">
              <div class="text-lg font-bold">Hustle XAU</div>
              <div class="text-xs text-text-tertiary">Arbitrage System</div>
            </div>
          </router-link>

          <!-- Desktop Navigation -->
          <div class="hidden lg:flex space-x-1" :class="{ 'lg:hidden': navbarCollapsed }">
            <router-link
              v-for="item in navItems"
              :key="item.path"
              :to="item.path"
              class="nav-link"
            >
              <component :is="item.icon" class="w-5 h-5 flex-shrink-0" />
              <span>{{ item.label }}</span>
            </router-link>
          </div>
        </div>

        <!-- Right Side -->
        <div class="flex items-center space-x-4">
          <!-- User Menu -->
          <div class="relative" ref="userMenuRef">
            <button
              @click="userMenuOpen = !userMenuOpen"
              class="flex items-center space-x-2 px-3 py-2 rounded-lg hover:bg-dark-50 transition-colors"
            >
              <div class="w-8 h-8 bg-gradient-to-br from-primary to-primary-hover rounded-full flex items-center justify-center">
                <span class="text-dark-300 font-bold text-sm">{{ userInitial }}</span>
              </div>
              <div class="hidden md:block text-left">
                <div class="text-sm font-medium">{{ user?.username }}</div>
                <div class="text-xs text-text-tertiary">{{ user?.email }}</div>
              </div>
              <svg class="w-4 h-4 text-text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            <!-- Dropdown Menu -->
            <transition
              enter-active-class="transition ease-out duration-100"
              enter-from-class="transform opacity-0 scale-95"
              enter-to-class="transform opacity-100 scale-100"
              leave-active-class="transition ease-in duration-75"
              leave-from-class="transform opacity-100 scale-100"
              leave-to-class="transform opacity-0 scale-95"
            >
              <div
                v-if="userMenuOpen"
                class="absolute right-0 mt-2 w-48 bg-dark-100 rounded-lg shadow-lg border border-border-primary py-1"
              >
                <button
                  @click="handleEditProfile"
                  class="w-full text-left px-4 py-2 text-sm hover:bg-dark-50 transition-colors flex items-center space-x-2"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  <span>编辑信息</span>
                </button>
                <button
                  @click="handleChangePassword"
                  class="w-full text-left px-4 py-2 text-sm hover:bg-dark-50 transition-colors flex items-center space-x-2"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                  </svg>
                  <span>修改密码</span>
                </button>
                <button
                  @click="handlePageManagement"
                  class="w-full text-left px-4 py-2 text-sm hover:bg-dark-50 transition-colors flex items-center space-x-2"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                  </svg>
                  <span>页面管理</span>
                </button>
                <div class="border-t border-border-secondary my-1"></div>
                <button
                  @click="handleLogout"
                  class="w-full text-left px-4 py-2 text-sm hover:bg-dark-50 transition-colors flex items-center space-x-2"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                  <span>退出登录</span>
                </button>
              </div>
            </transition>
          </div>

          <!-- Hide Entire Navbar Button -->
          <button
            @click="toggleNavbarVisibility"
            class="flex items-center justify-center p-2 rounded-lg hover:bg-dark-50 transition-colors"
            title="隐藏顶部导航栏"
          >
            <svg class="w-5 h-5 text-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>

          <!-- Mobile Menu Button -->
          <button
            @click="mobileMenuOpen = !mobileMenuOpen"
            class="lg:hidden p-2 rounded-lg hover:bg-dark-50 transition-colors"
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                v-if="!mobileMenuOpen"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 6h16M4 12h16M4 18h16"
              />
              <path
                v-else
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>
      </div>

      <!-- Mobile Menu -->
      <transition
        enter-active-class="transition ease-out duration-200"
        enter-from-class="transform opacity-0 -translate-y-2"
        enter-to-class="transform opacity-100 translate-y-0"
        leave-active-class="transition ease-in duration-150"
        leave-from-class="transform opacity-100 translate-y-0"
        leave-to-class="transform opacity-0 -translate-y-2"
      >
        <div v-if="mobileMenuOpen" class="lg:hidden py-4 space-y-1 border-t border-border-secondary">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            @click="mobileMenuOpen = false"
            class="mobile-nav-link"
          >
            <component :is="item.icon" class="w-5 h-5" />
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </transition>
    </div>
  </nav>

  <!-- Floating Show Navbar Button (when navbar is hidden) -->
  <button
    v-show="navbarHidden"
    @click="toggleNavbarVisibility"
    class="fixed bottom-4 left-4 z-50 p-3 bg-primary hover:bg-primary-hover rounded-lg shadow-lg transition-colors lg:right-4 lg:left-auto"
    title="显示顶部导航栏"
  >
    <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  </button>

  <!-- Modals -->
  <EditProfileModal :isOpen="editProfileModalOpen" @close="editProfileModalOpen = false" @updated="handleProfileUpdated" />
  <ChangePasswordModal :isOpen="changePasswordModalOpen" @close="changePasswordModalOpen = false" @updated="handlePasswordChanged" />

  <!-- Page Management Modal -->
  <div v-if="pageManagementModalOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50" @click.self="pageManagementModalOpen = false">
    <div class="bg-dark-100 rounded-lg shadow-xl border border-border-primary p-6 w-full max-w-md">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold">页面管理</h3>
        <button @click="pageManagementModalOpen = false" class="text-text-tertiary hover:text-text-primary">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div class="space-y-2">
        <div v-for="item in allNavItems" :key="item.path" class="flex items-center justify-between p-3 bg-dark-200 rounded-lg">
          <span class="text-sm">{{ item.label }}</span>
          <button
            @click="togglePageVisibility(item.path)"
            :class="[
              'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
              pageVisibility[item.path] ? 'bg-primary' : 'bg-gray-600'
            ]"
          >
            <span
              :class="[
                'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                pageVisibility[item.path] ? 'translate-x-5' : 'translate-x-1'
              ]"
            />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notification'
import EditProfileModal from '@/components/modals/EditProfileModal.vue'
import ChangePasswordModal from '@/components/modals/ChangePasswordModal.vue'
import api from '@/services/api'

const router = useRouter()
const authStore = useAuthStore()
const notificationStore = useNotificationStore()
const mobileMenuOpen = ref(false)
const userMenuOpen = ref(false)
const userMenuRef = ref(null)
const editProfileModalOpen = ref(false)
const changePasswordModalOpen = ref(false)
const pageManagementModalOpen = ref(false)
const navbarCollapsed = ref(localStorage.getItem('navbarCollapsed') === 'true')

// 检查是否是首次加载且屏幕分辨率较小
const isFirstLoad = localStorage.getItem('navbarHidden') === null
const isSmallScreen = window.innerWidth <= 1366 && window.innerHeight <= 768
const navbarHidden = ref(
  isFirstLoad && isSmallScreen
    ? true
    : localStorage.getItem('navbarHidden') === 'true'
)

const user = computed(() => authStore.user)
const userInitial = computed(() => user.value?.username?.charAt(0).toUpperCase() || 'U')

// 初始化页面可见性状态
const initPageVisibility = () => {
  const saved = localStorage.getItem('pageVisibility')
  if (saved) {
    return JSON.parse(saved)
  }

  // 首次加载：在1366×768分辨率下，Risk页面默认隐藏
  const isSmallScreen = window.innerWidth <= 1366 && window.innerHeight <= 768
  const defaultVisibility = {
    '/': true,
    '/trading': true,
    '/pending-orders': true,
  }

  // 保存默认状态
  localStorage.setItem('pageVisibility', JSON.stringify(defaultVisibility))
  return defaultVisibility
}

const pageVisibility = ref(initPageVisibility())

// 所有可用的导航项（仅保留交易操作面板功能，管理功能已迁移至 admin.hustle2026.xyz）
const allNavItems = [
  {
    path: '/',
    label: '控制面板',
    icon: 'DashboardIcon',
  },
  {
    path: '/trading',
    label: '交易历史数据',
    icon: 'TradingIcon',
  },
  {
    path: '/pending-orders',
    label: '挂单查询',
    icon: 'PendingOrdersIcon',
  },
]

// 过滤出可见的导航项
const navItems = computed(() => {
  return allNavItems.filter(item => pageVisibility.value[item.path] !== false)
})

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  // 如果是首次加载且自动隐藏，保存状态
  if (navbarHidden.value && isFirstLoad && isSmallScreen) {
    localStorage.setItem('navbarHidden', 'true')
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

function handleClickOutside(event) {
  if (userMenuRef.value && !userMenuRef.value.contains(event.target)) {
    userMenuOpen.value = false
  }
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

function handleEditProfile() {
  userMenuOpen.value = false
  editProfileModalOpen.value = true
}

function handleChangePassword() {
  userMenuOpen.value = false
  changePasswordModalOpen.value = true
}

function handlePageManagement() {
  userMenuOpen.value = false
  pageManagementModalOpen.value = true
}

function togglePageVisibility(path) {
  pageVisibility.value[path] = !pageVisibility.value[path]
  localStorage.setItem('pageVisibility', JSON.stringify(pageVisibility.value))
}

function handleProfileUpdated() {
  // Profile was successfully updated
  console.log('Profile updated successfully')
}

function handlePasswordChanged() {
  // Password was successfully changed
  console.log('Password changed successfully')
}

function toggleAlertSound() {
  notificationStore.toggleAlertSound(!notificationStore.alertSoundEnabled)
}

function toggleSingleLegAlert() {
  notificationStore.toggleSingleLegAlert(!notificationStore.singleLegAlertEnabled)
}

function toggleNavbar() {
  navbarCollapsed.value = !navbarCollapsed.value
  localStorage.setItem('navbarCollapsed', navbarCollapsed.value.toString())
}

function toggleNavbarVisibility() {
  navbarHidden.value = !navbarHidden.value
  localStorage.setItem('navbarHidden', navbarHidden.value.toString())
}

// Icon components
const DashboardIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" /></svg>`
}

const TradingIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>`
}

const PendingOrdersIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" /></svg>`
}

const StrategiesIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>`
}

const PositionsIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>`
}

const AccountsIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" /></svg>`
}

const RiskIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>`
}

const SystemIcon = {
  template: `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>`
}
</script>

<style scoped>
.nav-link {
  @apply flex items-center space-x-1 px-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-dark-50 transition-all duration-200;
  height: 40px;
  min-width: fit-content;
  white-space: nowrap;
}

.router-link-active.nav-link {
  @apply text-primary bg-primary/10 font-medium;
}

.mobile-nav-link {
  @apply flex items-center space-x-3 px-4 rounded-lg text-text-secondary hover:text-text-primary hover:bg-dark-50 transition-colors;
  height: 40px;
  min-width: fit-content;
}

.router-link-active.mobile-nav-link {
  @apply text-primary bg-primary/10 font-medium;
}

/* PC端优化 - 缩小提醒音和单腿提醒按钮 */
@media (min-width: 1024px) {
  /* 缩小开关容器 */
  .xl\:flex > div.bg-dark-200 {
    padding: 0.25rem 0.5rem !important;
  }

  /* 缩小图标 */
  .xl\:flex > div.bg-dark-200 svg {
    width: 0.75rem !important;
    height: 0.75rem !important;
  }

  /* 缩小文字 */
  .xl\:flex > div.bg-dark-200 span.text-sm {
    font-size: 0.7rem !important;
  }

  /* 缩小开关按钮 */
  .xl\:flex > div.bg-dark-200 button {
    height: 0.875rem !important;
    width: 1.5rem !important;
  }

  /* 缩小开关按钮内的圆点 */
  .xl\:flex > div.bg-dark-200 button span {
    height: 0.625rem !important;
    width: 0.625rem !important;
  }

  /* 调整开关按钮圆点的位置 */
  .xl\:flex > div.bg-dark-200 button span.translate-x-5 {
    transform: translateX(0.625rem) !important;
  }

  .xl\:flex > div.bg-dark-200 button span.translate-x-1 {
    transform: translateX(0.125rem) !important;
  }
}
</style>