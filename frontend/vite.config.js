import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',  // Listen on all network interfaces
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://172.31.5.62:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://172.31.5.62:8000',
        ws: true,
      },
    },
  },
})
