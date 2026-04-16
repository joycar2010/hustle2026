import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    root: path.resolve(__dirname, 'src-admin'),
    define: {
      '__BUILD_TS__': JSON.stringify(Date.now().toString()),
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(
        env.VITE_ADMIN_API_BASE_URL || env.VITE_API_BASE_URL || 'https://go.hustle2026.xyz'
      ),
      'import.meta.env.VITE_WS_URL': JSON.stringify(
        env.VITE_WS_URL || 'wss://go.hustle2026.xyz'
      ),
    },
    build: {
      outDir: path.resolve(__dirname, 'dist-admin'),
      emptyOutDir: true,
      rollupOptions: {
        output: {
          chunkFileNames: 'assets/[name]-[hash].js',
          entryFileNames: 'assets/[name]-[hash].js',
          assetFileNames: 'assets/[name]-[hash][extname]',
        },
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src-admin'),
        '@src': path.resolve(__dirname, './src'),
      },
    },
  }
})
