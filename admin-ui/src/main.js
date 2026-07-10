import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/theme.css'
import App from './App.vue'
import router from './router'

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')

// 工具:数字格式化 + 正负色(全局挂载,视图内 import 亦可)
export const fmt = (v, d = 2) => (v == null ? '–' : (+v).toFixed(d))
export const cls = (v) => (v == null ? '' : (v >= 0 ? 'pos' : 'neg'))
