import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  define: {
    // 每次构建注入时间戳，确保至少有一个模块内容变化，迫使 Rollup 生成新 hash
    '__BUILD_TS__': JSON.stringify(Date.now().toString()),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // 强制清空输出目录，避免旧文件残留
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // 使用内容 hash（默认），配合 define 时间戳确保每次构建 hash 不同
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': { target: 'http://172.31.5.62:8000', changeOrigin: true },
      '/ws':  { target: 'ws://172.31.5.62:8000', ws: true },
    },
  },
})
