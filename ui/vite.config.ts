import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
// C4：把应用版本注入前端（Snapshot v1 `source.appVersion` 需要真实版本，
// 而不是在代码里另写一份会漂移的硬编码副本）。
import pkg from './package.json'

// Tauri dev 上下文（前端跑在 tauri devUrl 上）
const host = process.env.TAURI_DEV_HOST

export default defineConfig({
  plugins: [vue()],
  define: {
    __PW_APP_VERSION__: JSON.stringify(pkg.version),
  },
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
    // 不清空输出目录：index.html 每次整体重写并指向最新 hash 资源，旧 chunk 仅残留占用；
    // 需要彻底清理时手动删 dist（2026-09-14：规避沙箱批量删除保护对构建的误伤）。
    emptyOutDir: false,
  },
})
