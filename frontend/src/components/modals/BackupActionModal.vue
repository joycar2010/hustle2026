<template>
  <div v-if="show" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click.self="close">
    <div class="bg-dark-200 rounded-lg p-6 w-full max-w-md">
      <div class="flex justify-between items-center mb-6">
        <h3 class="text-xl font-bold">{{ title }}</h3>
        <button @click="close" class="text-gray-400 hover:text-white">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="space-y-3">
        <button
          @click="select('github')"
          class="w-full flex items-center space-x-4 bg-dark-100 hover:bg-dark-50 rounded-lg p-4 transition-colors text-left"
        >
          <div class="flex-shrink-0 w-10 h-10 bg-gray-700 rounded-full flex items-center justify-center">
            <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
            </svg>
          </div>
          <div>
            <div class="font-medium">{{ githubLabel }}</div>
            <div class="text-sm text-gray-400">{{ githubDesc }}</div>
          </div>
        </button>

        <button
          @click="select('server')"
          class="w-full flex items-center space-x-4 bg-dark-100 hover:bg-dark-50 rounded-lg p-4 transition-colors text-left"
        >
          <div class="flex-shrink-0 w-10 h-10 bg-blue-700 rounded-full flex items-center justify-center">
            <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
            </svg>
          </div>
          <div>
            <div class="font-medium">{{ serverLabel }}</div>
            <div class="text-sm text-gray-400">{{ serverDesc }}</div>
          </div>
        </button>
      </div>

      <div class="flex justify-end mt-6">
        <button @click="close" class="btn-secondary">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  show: Boolean,
  title: { type: String, default: '选择操作方式' },
  githubLabel: { type: String, default: 'GitHub' },
  githubDesc: { type: String, default: '' },
  serverLabel: { type: String, default: '服务器' },
  serverDesc: { type: String, default: '' },
})

const emit = defineEmits(['close', 'select'])

function select(type) {
  emit('select', type)
  emit('close')
}

function close() {
  emit('close')
}
</script>

<style scoped>
.btn-secondary {
  @apply inline-flex items-center px-4 py-2 bg-dark-200 hover:bg-dark-100 text-text-primary rounded-lg transition-colors font-medium;
}
</style>
