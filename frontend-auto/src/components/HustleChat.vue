<template>
  <div>
    <!-- Trigger button -->
    <button v-if="!open" @click="toggle"
      class="fixed bottom-6 right-6 z-50 w-12 h-12 bg-primary text-dark-300 rounded-full flex items-center justify-center hover:bg-primary-hover transition-colors"
      title="Hustle AI 助手">
      <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
      </svg>
    </button>

    <!-- Chat panel -->
    <div v-if="open"
      class="fixed bottom-6 right-6 z-50 w-[400px] h-[520px] max-sm:inset-0 max-sm:w-full max-sm:h-full max-sm:rounded-none max-sm:border-0 bg-dark-100 border border-border-primary rounded-xl flex flex-col overflow-hidden">
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-border-primary bg-dark-200">
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded bg-primary flex items-center justify-center text-dark-300 font-bold text-xs">H</div>
          <span class="font-semibold text-sm">Hustle</span>
          <span class="text-[10px] px-1.5 py-0.5 bg-dark-100 rounded text-text-tertiary">AI 助手</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-[10px] text-text-tertiary">{{ remaining }}/20</span>
          <button @click="toggle" class="text-text-tertiary hover:text-text-primary text-lg leading-none">&times;</button>
        </div>
      </div>

      <!-- Messages -->
      <div ref="msgsRef" class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        <div v-if="!messages.length" class="text-center text-text-tertiary text-xs py-8">
          你好！我是 Hustle，OpenCLAW 控制台 AI 助手。<br>有任何使用问题都可以问我。
        </div>
        <div v-for="msg in messages" :key="msg.id || msg._id"
          :class="msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'">
          <div :class="[
            'max-w-[85%] px-3 py-2 rounded-lg text-xs leading-relaxed whitespace-pre-wrap',
            msg.role === 'user'
              ? 'bg-primary/15 text-text-primary border border-primary/30'
              : 'bg-dark-200 text-text-primary border border-border-primary'
          ]">{{ msg.content }}<span v-if="msg._streaming" class="inline-block w-1.5 h-3.5 bg-primary/60 ml-0.5 animate-pulse align-middle"></span></div>
        </div>
      </div>

      <!-- Input -->
      <div class="px-4 py-3 border-t border-border-primary bg-dark-200">
        <div class="flex gap-2">
          <input v-model="input" @keydown.enter.prevent="send" :disabled="sending"
            placeholder="输入问题…"
            class="flex-1 bg-dark-100 border border-border-primary rounded-lg px-3 py-2 text-xs text-text-primary placeholder-text-tertiary outline-none focus:border-primary">
          <button @click="send" :disabled="sending || !input.trim()"
            class="px-4 py-2 bg-primary text-dark-300 rounded-lg text-xs font-semibold hover:bg-primary-hover disabled:opacity-40 transition-colors whitespace-nowrap">
            {{ sending ? '…' : '发送' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import api from '@/api'

const open = ref(false)
const input = ref('')
const messages = ref([])
const sending = ref(false)
const remaining = ref(20)
const msgsRef = ref(null)
let loaded = false
let idCounter = 0

function scrollBottom() {
  nextTick(() => {
    if (msgsRef.value) msgsRef.value.scrollTop = msgsRef.value.scrollHeight
  })
}

async function loadHistory() {
  if (loaded) return
  try {
    const r = await api.get('/api/v1/agent/chat/history', { params: { site: 'auto' } })
    messages.value = r.data.messages || []
    remaining.value = r.data.remaining ?? 20
    loaded = true
    scrollBottom()
  } catch {}
}

function toggle() {
  open.value = !open.value
  if (open.value) { loadHistory() }
}

async function send() {
  const msg = input.value.trim()
  if (!msg || sending.value) return
  if (remaining.value <= 0) { alert('每小时最多提问 20 次，请稍后再试'); return }

  input.value = ''
  sending.value = true

  const userMsg = { _id: ++idCounter, role: 'user', content: msg }
  messages.value.push(userMsg)
  scrollBottom()

  const assistantMsg = { _id: ++idCounter, role: 'assistant', content: '', _streaming: true }
  messages.value.push(assistantMsg)
  scrollBottom()

  remaining.value = Math.max(0, remaining.value - 1)

  try {
    const token = localStorage.getItem('access_token')
    const resp = await fetch('/api/v1/agent/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
      },
      body: JSON.stringify({ message: msg, site: 'auto' }),
    })

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      assistantMsg.content = err.detail || '请求失败，请重试'
      assistantMsg._streaming = false
      sending.value = false
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      while (buffer.includes('\n')) {
        const idx = buffer.indexOf('\n')
        const line = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 1)

        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') break

        try {
          const obj = JSON.parse(payload)
          if (obj.content) {
            assistantMsg.content += obj.content
            scrollBottom()
          }
          if (obj.error) {
            assistantMsg.content += '\n⚠ ' + obj.error
          }
        } catch {}
      }
    }
  } catch (e) {
    assistantMsg.content = assistantMsg.content || '网络错误，请重试'
  } finally {
    assistantMsg._streaming = false
    sending.value = false
    scrollBottom()
  }
}
</script>
