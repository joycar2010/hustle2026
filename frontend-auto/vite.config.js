import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    define: {
      '__BUILD_TS__': JSON.stringify(Date.now().toString()),
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(env.VITE_API_BASE_URL || ''),
      'import.meta.env.VITE_WS_URL': JSON.stringify(env.VITE_WS_URL || 'wss://auto.hustle2026.xyz'),
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      rollupOptions: { output: {
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      }},
    },
    resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  }
})
