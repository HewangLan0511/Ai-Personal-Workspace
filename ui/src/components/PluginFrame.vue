<script setup lang="ts">
/**
 * 插件沙箱 iframe（契约 3.2.7 / 12 §A4）。
 *
 * - `sandbox` 且**不带** `allow-same-origin`：opaque origin，与宿主隔离；
 * - 加载 `http://pwplugin.localhost/<pluginId>/<entry>`（core serve_file 路径守卫）；
 * - **10s 内未报告 ready → 标记超时**（可重试重启）；
 * - iframe 内 `onerror` 由插件自己捕获后经 `system.reportError`... 不，
 *   契约口径：插件页面挂掉时宿主感知不到内部错误，故插件 SDK 约定在
 *   `window.onerror` 里 postMessage `{__pwPlugin:true, crash:{reason}}`；
 *   宿主收到即上报 core `plugin_crash` 并标记"已停止"。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { pluginCrash } from '@/api/pluginService'
import { registerFrame, unregisterFrame } from '@/plugin/pluginHost'

const props = defineProps<{
  pluginId: string
  entry: string
  height?: string
}>()

const frameRef = ref<HTMLIFrameElement | null>(null)
const state = ref<'loading' | 'ready' | 'timeout' | 'stopped'>('loading')
const readyTimer = ref<number | null>(null)

const src = computed(
  () => `http://pwplugin.localhost/${encodeURIComponent(props.pluginId)}/${props.entry.replace(/^\/+/, '')}`,
)

function onMessage(ev: MessageEvent): void {
  if (ev.origin !== 'http://pwplugin.localhost') return
  const data = ev.data as { __pwPlugin?: boolean; ready?: boolean; crash?: { reason?: string } } | undefined
  if (!data || data.__pwPlugin !== true || ev.source !== frameRef.value?.contentWindow) return
  if (data.ready && state.value === 'loading') {
    state.value = 'ready'
    if (readyTimer.value) window.clearTimeout(readyTimer.value)
  }
  if (data.crash) {
    state.value = 'stopped'
    void pluginCrash(props.pluginId, String(data.crash.reason ?? 'unknown'))
  }
}

function restart(): void {
  state.value = 'loading'
  if (frameRef.value) {
    // 重新赋 src 触发重载
    const cur = frameRef.value.src
    frameRef.value.src = cur
    armReadyTimer()
  }
}

function armReadyTimer(): void {
  if (readyTimer.value) window.clearTimeout(readyTimer.value)
  readyTimer.value = window.setTimeout(() => {
    if (state.value === 'loading') state.value = 'timeout'
  }, 10_000)
}

onMounted(() => {
  window.addEventListener('message', onMessage)
  registerFrame(frameRef.value?.contentWindow ?? null, props.pluginId)
  armReadyTimer()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  unregisterFrame(frameRef.value?.contentWindow ?? null)
  if (readyTimer.value) window.clearTimeout(readyTimer.value)
})
</script>

<template>
  <div class="plugin-frame">
    <div v-if="state !== 'ready'" class="plugin-frame-mask">
      <span v-if="state === 'loading'">插件加载中…</span>
      <template v-else-if="state === 'timeout'">
        <span>加载超时（10s 未报告 ready）</span>
        <button type="button" @click="restart">重试</button>
      </template>
      <template v-else>
        <span>插件已停止（崩溃上报已记录）</span>
        <button type="button" @click="restart">重启</button>
      </template>
    </div>
    <iframe
      ref="frameRef"
      :src="src"
      sandbox="allow-scripts"
      class="plugin-frame-host"
      :style="{ height: height ?? '100%' }"
      @load="registerFrame(($event.target as HTMLIFrameElement).contentWindow ?? null, pluginId)"
    />
  </div>
</template>

<style scoped>
.plugin-frame {
  position: relative;
  width: 100%;
  min-height: 120px;
}

.plugin-frame-host {
  width: 100%;
  border: 0;
  display: block;
}

.plugin-frame-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--pw-text-secondary, #888);
  background: var(--pw-bg-subtle, rgba(0, 0, 0, 0.03));
  z-index: 1;
  pointer-events: auto;
}
</style>
