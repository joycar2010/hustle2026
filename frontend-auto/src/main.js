import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

// Open WebSocket stream once token is available (after login or on reload)
import { useWsStream } from './stores/wsStream.js'
const ws = useWsStream()
if (localStorage.getItem('access_token')) ws.connect()
window.addEventListener('storage', (e) => {
  if (e.key === 'access_token') {
    if (e.newValue) ws.connect()
    else ws.disconnect()
  }
})
