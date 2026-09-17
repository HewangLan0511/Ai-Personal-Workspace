<script setup lang="ts">
/**
 * 模式栏（06 §5 · F-40）：常驻显示当前模式，支持快速切换与退出。
 *
 * 数据源：
 *  - `running`（本次进程内正在运行的模式）
 *  - `configured`（config 里"上次使用过的模式"，06 §4 用于一键恢复）
 * 两者分开显示 —— "上次用过"与"现在正开着"是两件事。
 */
import { onMounted, onUnmounted, ref } from 'vue'

import { modeApi, type WorkMode } from '@/api/modeService'

const modes = ref<WorkMode[]>([])
const running = ref<string | null>(null)
const configured = ref('')
const busy = ref(false)
const message = ref('')

let timer: number | undefined

async function refresh() {
  try {
    const c = await modeApi.current()
    running.value = c.running
    configured.value = typeof c.configured === 'string' ? c.configured : ''
    if (modes.value.length === 0) modes.value = await modeApi.list()
  } catch {
    /* 降级环境（浏览器）无核心能力，静默 */
  }
}

onMounted(async () => {
  await refresh()
  timer = window.setInterval(refresh, 5000)
})
onUnmounted(() => window.clearInterval(timer))

async function switchTo(name: string) {
  if (!name) return
  const m = modes.value.find((x) => x.name === name)
  if (!m) return
  busy.value = true
  message.value = ''
  try {
    const out = await modeApi.apply(m.id)
    message.value = `已进入 ${out.modeName}`
    await refresh()
  } catch (err) {
    message.value = String(err)
  } finally {
    busy.value = false
    window.setTimeout(() => (message.value = ''), 4000)
  }
}

async function exitMode() {
  try {
    await modeApi.exit()
    await refresh()
  } catch (err) {
    message.value = String(err)
  }
}

async function restore() {
  try {
    const out = await modeApi.restore()
    message.value = `已恢复 ${out.modeName}`
    await refresh()
  } catch (err) {
    message.value = String(err)
  }
}
</script>

<template>
  <div class="mode-bar">
    <span class="mode-bar__label">模式</span>
    <template v-if="running">
      <strong class="mode-bar__current">{{ running }}</strong>
      <button type="button" class="mode-bar__exit" @click="exitMode">退出</button>
    </template>
    <template v-else>
      <span class="mode-bar__none">未进入</span>
      <button v-if="configured" type="button" class="mode-bar__restore" @click="restore">
        恢复「{{ configured }}」
      </button>
    </template>

    <select class="mode-bar__select" :disabled="busy" @change="switchTo(($event.target as HTMLSelectElement).value)">
      <option value="">快速切换…</option>
      <option v-for="m in modes" :key="m.id" :value="m.name">{{ m.name }}</option>
    </select>

    <span v-if="message" class="mode-bar__msg">{{ message }}</span>
  </div>
</template>

<style scoped>
.mode-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  font-size: 12px;
  min-height: 30px;
}

.mode-bar__label {
  color: var(--text-dim);
}

.mode-bar__current {
  color: var(--ok);
}

.mode-bar__none {
  color: var(--text-dim);
}

.mode-bar__select {
  max-width: 200px;
}

.mode-bar__msg {
  color: var(--accent);
}

.mode-bar__restore {
  font-size: 12px;
}
</style>
