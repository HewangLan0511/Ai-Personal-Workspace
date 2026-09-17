<script setup lang="ts">
/**
 * 桌面小组件窗口内容（阶段9 · 12 §B）。
 *
 * 挂载方式：core 以 `index.html?pwWindow=desktop-widget` 创建独立窗口，
 * `main.ts` 检测该查询参数后挂载本组件（不经路由、不带侧栏）。
 * 顶部为拖动区（data-tauri-drag-region，需 core:window:allow-start-dragging 权限）；
 * 边界由 core 在窗口 CloseRequested 时落盘，这里不做高频回写。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import PluginFrame from '@/components/PluginFrame.vue'
import { PLUGIN_NOTIFY_EVENT, startPluginHost, stopPluginHost } from '@/plugin/pluginHost'
import { pluginsList, widgetSetAlwaysOnTop, widgetStatus, type PluginRow } from '@/api/pluginService'

const widgetPlugins = ref<PluginRow[]>([])
const notifications = ref<string[]>([])
const status = ref<{ alwaysOnTop: boolean } | null>(null)

function pushNotify(detail: { title?: string; body?: string }): void {
  notifications.value.unshift(`${detail.title ?? ''} ${detail.body ?? ''}`.trim())
  if (notifications.value.length > 5) notifications.value.pop()
}

onMounted(async () => {
  startPluginHost()
  window.addEventListener(PLUGIN_NOTIFY_EVENT, (ev) => {
    pushNotify((ev as CustomEvent).detail ?? {})
  })
  const all = await pluginsList().catch(() => [] as PluginRow[])
  widgetPlugins.value = all.filter((p) => p.enabled && p.ui && p.ui.type === 'widget')
  status.value = await widgetStatus().catch(() => null)
})

onBeforeUnmount(() => {
  stopPluginHost()
})

async function onAot(): Promise<void> {
  const on = !(status.value?.alwaysOnTop ?? false)
  await widgetSetAlwaysOnTop(on).catch(() => null)
  status.value = { ...(status.value ?? { alwaysOnTop: on } as { alwaysOnTop: boolean }), alwaysOnTop: on }
}

function onClose(): void {
  void widgetToggleSafe()
}

async function widgetToggleSafe(): Promise<void> {
  const { widgetToggle } = await import('@/api/pluginService')
  await widgetToggle().catch(() => null)
}
</script>

<template>
  <div class="widget-window">
    <header class="widget-bar" data-tauri-drag-region>
      <span class="widget-title" data-tauri-drag-region>小组件</span>
      <button type="button" class="widget-btn" title="置顶" @click="onAot">
        {{ status?.alwaysOnTop ? '📌' : '📍' }}
      </button>
      <button type="button" class="widget-btn" title="关闭" @click="onClose">✕</button>
    </header>

    <div v-if="notifications.length" class="widget-notify">
      <div v-for="(n, i) in notifications" :key="i" class="widget-notify-item">{{ n }}</div>
    </div>

    <div v-if="!widgetPlugins.length" class="widget-empty">
      没有启用中的小组件插件。
      <span class="widget-empty-hint">在主窗口「插件」页启用带 UI 的插件。</span>
    </div>

    <div v-else class="widget-list">
      <PluginFrame
        v-for="p in widgetPlugins"
        :key="p.pluginId"
        :plugin-id="p.pluginId"
        :entry="p.entry"
        height="180px"
      />
    </div>
  </div>
</template>

<style scoped>
.widget-window {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--pw-bg, #fafafa);
  color: var(--pw-text, #222);
  font-size: 13px;
  border: 1px solid var(--pw-border, rgba(0, 0, 0, 0.12));
  border-radius: 8px;
  overflow: hidden;
}

.widget-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  user-select: none;
  cursor: grab;
  background: var(--pw-bg-subtle, rgba(0, 0, 0, 0.04));
}

.widget-title {
  flex: 1;
  font-weight: 600;
  cursor: grab;
}

.widget-btn {
  border: 0;
  background: transparent;
  cursor: pointer;
  padding: 2px 4px;
}

.widget-notify {
  padding: 4px 8px;
  font-size: 12px;
  color: #8a6d3b;
  background: rgba(240, 200, 100, 0.18);
}

.widget-notify-item {
  padding: 1px 0;
}

.widget-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
  justify-content: center;
  color: var(--pw-text-secondary, #999);
}

.widget-list {
  flex: 1;
  overflow: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
