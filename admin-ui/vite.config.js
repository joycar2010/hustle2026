import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1600,
    // hash 文件名(长缓存+防缓存吞部署)+ vendor 分包(qh L6 同款)
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
        manualChunks(id){
          if(!id.includes('node_modules')) return
          if(id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
          if(id.includes('element-plus') || id.includes('@element-plus')) return 'vendor-element'
          if(id.includes('/vue') || id.includes('pinia') || id.includes('vue-router')) return 'vendor-vue'
          return 'vendor'
        }
      }
    }
  },
  server: { port: 5180 }
})
