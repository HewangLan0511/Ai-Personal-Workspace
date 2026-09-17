<script setup lang="ts">
import { onMounted } from 'vue'

import { connection, inTauri, invokeCore } from '@/api/client'
import { useSettingsStore } from '@/stores/settings'
import { logger } from '@/utils/logger'

const settings = useSettingsStore()
onMounted(() => settings.load())

/**
 * 最小化主窗口（04 §2 顶栏 `[设置] [最小化]`）。
 *
 * 补完 REVIEW-002 R-06：此前 core 侧 `minimize_window` 命令**已经存在**，
 * 但 UI 零调用 —— 属"命令在、按钮没接"的半成品，功能实际不可用。
 * 通道按 ADR-001 归 Rust（core 的 `minimize_window`），前端只发这一个无参数动作。
 *
 * 浏览器直开（vite dev，无 Tauri 容器）时没有窗口可最小化 ⇒ 按钮置灰，
 * 而不是点了没反应（失败要可见，不能静默）。
 */
const canMinimize = inTauri()

async function onMinimize(): Promise<void> {
  try {
    await invokeCore<void>('minimize_window')
  } catch (err) {
    logger.error('window', `minimize_window 失败：${String(err)}`)
  }
}
</script>

<template>
  <header class="app-topbar">
    <strong>Personal Workspace</strong>
    <div class="topbar-right" style="display: flex; gap: 10px; align-items: center;">
      <span
        v-if="!connection.online"
        style="color: var(--danger); font-size: 12px;"
        title="core 未连接，所有持久化降级到本地"
      >⚠ 降级模式</span>
      <button
        type="button"
        :disabled="!canMinimize"
        :title="canMinimize ? '最小化' : '浏览器环境下无窗口可最小化'"
        @click="onMinimize"
      >最小化</button>
      <router-link to="/settings">
        <button>设置</button>
      </router-link>
    </div>
  </header>
</template>