import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as Icons from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import i18n from './locales'
import './styles/theme.scss'
import './styles/mix-tokens.css'
import longpress from './directives/longpress'
import FIcon from './components/FIcon.vue'
import { installTips } from './tips'

const app = createApp(App)
for (const [k, v] of Object.entries(Icons)) app.component(k, v)
app.component('FIcon', FIcon)            // 扁平功能图标(去 emoji,currentColor 自适应)
app.directive('longpress', longpress)   // L2 长按交互指令(全局)
app.use(createPinia()).use(router).use(ElementPlus).use(i18n)
app.mount('#app')
installTips()   // 全站悬停功能说明(按文本匹配字典挂 title, MutationObserver 覆盖动态渲染)

// L4 PWA Service Worker 注册(生产环境; 静态壳缓存, 严格绕开 /api /ws 实时接口)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(()=>{})
  })
}

// 全局防浏览器凭证回填: 给所有未显式声明 autocomplete 的 input 兜底 off
// (密码/密钥框模板里已单独设 new-password, 此处不覆盖已有值)。
// MutationObserver 捕获后续动态渲染(模态框/表格内联输入)的新 input。
;(function preventAutofill(){
  const patch=(root)=>{
    (root.querySelectorAll ? root.querySelectorAll('input') : []).forEach(inp=>{
      if(!inp.getAttribute('autocomplete')) inp.setAttribute('autocomplete','off')
      // 关闭浏览器/密码管理器的记忆与拼写建议
      if(!inp.getAttribute('data-af-done')){
        inp.setAttribute('autocorrect','off'); inp.setAttribute('spellcheck','false')
        if(inp.type==='password' && inp.getAttribute('autocomplete')==='off') inp.setAttribute('autocomplete','new-password')
        inp.setAttribute('data-af-done','1')
      }
    })
  }
  const run=()=>patch(document)
  if(document.readyState!=='loading') run(); else document.addEventListener('DOMContentLoaded',run)
  const mo=new MutationObserver(muts=>{
    for(const m of muts){ for(const n of m.addedNodes){ if(n.nodeType===1) patch(n) } }
  })
  mo.observe(document.body,{childList:true,subtree:true})
})()
