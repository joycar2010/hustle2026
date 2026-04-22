import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router/index.js'
import '@src/assets/main.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

import { useWsStream } from './stores/wsStream.js'
const _ws = useWsStream()
if (localStorage.getItem('www_token')) _ws.connect()
_ws.subscribe('site.status')
window.addEventListener('storage', (e) => { if (e.key === 'www_token') { e.newValue ? _ws.connect() : _ws.disconnect() } })
