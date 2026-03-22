import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    root: path.resolve(__dirname, 'src-www'),
    build: {
      outDir: path.resolve(__dirname, 'dist-www'),
      emptyOutDir: true,
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src-www'),
        '@src': path.resolve(__dirname, './src'),
      },
    },
    define: {
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(
        env.VITE_API_BASE_URL || 'https://go.hustle2026.xyz'
      ),
      'import.meta.env.VITE_WS_URL': JSON.stringify(
        env.VITE_WS_URL || 'wss://go.hustle2026.xyz'
      ),
    },
  }
})
