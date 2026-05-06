import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api': 'http://coin.hustle2026.xyz',
      '/ws': { target: 'ws://coin.hustle2026.xyz', ws: true },
    },
  },
  build: {
    outDir: '../python-business/static/spa',
    emptyOutDir: true,
  },
})
