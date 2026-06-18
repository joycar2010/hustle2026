import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  base: '/admin/',
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://coin.hustle2026.xyz',
    },
  },
  build: {
    outDir: '../python-business/static/admin-spa',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('lightweight-charts')) return 'charts'
            if (id.includes('react') || id.includes('scheduler')) return 'vendor'
          }
        },
      },
    },
  },
})
