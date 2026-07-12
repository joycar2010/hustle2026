import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
    // L6: 供应商分包 — element-plus / echarts / vue 全家桶各自独立 chunk,
    // 首屏只载入口+当前懒加载路由; 大库长缓存不随业务改动失效, 移动端二次访问更快。
    rollupOptions: {
      output: {
        manualChunks(id){
          if(!id.includes('node_modules')) return
          if(id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
          if(id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element'
          if(id.includes('/vue') || id.includes('pinia') || id.includes('@intlify') || id.includes('vue-router') || id.includes('vue-i18n')) return 'vendor-vue'
          return 'vendor'
        }
      }
    }
  },
  server: { port: 5180 }
})
