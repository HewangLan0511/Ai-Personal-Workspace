import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Tauri dev 上下文（前端跑在 tauri devUrl 上）
const host = process.env.TAURI_DEV_HOST

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // Tauri 加载本地依赖时禁用自动刷新造成干扰（Tauri 官方推荐配置）
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: host || 'localhost',
    watch: {
      ignored: ['**/core/**'],
    },
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: {
    target: 'es2022',
    minify: 'esbuild',
    sourcemap: false,
  },
})
