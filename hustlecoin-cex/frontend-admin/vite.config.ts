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
  },
})
