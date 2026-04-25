<template>
  <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <template v-if="name === 'dashboard'">
      <rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>
    </template>
    <template v-else-if="name === 'signal'">
      <line x1="2" y1="20" x2="2.01" y2="20"/><line x1="7" y1="20" x2="7" y2="16"/><line x1="12" y1="20" x2="12" y2="12"/><line x1="17" y1="20" x2="17" y2="8"/><line x1="22" y1="20" x2="22" y2="4"/>
    </template>
    <template v-else-if="name === 'chart'">
      <polyline points="3 21 3 3"/><polyline points="3 21 21 21"/><polyline points="7 16 11 12 15 16 20 11"/>
    </template>
    <template v-else-if="name === 'gear'">
      <circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
    </template>
    <template v-else-if="name === 'exchange'">
      <polyline points="7 4 7 16"/><polyline points="3 8 7 4 11 8"/><polyline points="17 20 17 8"/><polyline points="13 16 17 20 21 16"/>
    </template>
    <template v-else-if="name === 'users'">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>
    </template>
    <template v-else-if="name === 'cog'">
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94L14.7 6.3z"/>
    </template>
  </svg>
</template>

<script setup>
defineProps({ name: { type: String, required: true } })
</script>
