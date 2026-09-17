<script setup lang="ts">
/**
 * 布局管理（阶段3 / 07 §6 UI）。
 *
 * 三件事：选布局 → 看预览 → 一键应用。
 * 预览用**归一化坐标**直接画（0~1 映射到画布），所以预览比例与实际排布永远一致
 * —— 不需要另写一套像素换算（那必然与 core 漂移）。
 */
import { computed, onMounted, ref } from 'vue'

import { layoutApi, type ApplyOutcome, type Layout, type MonitorInfo } from '@/api/layoutService'

const layouts = ref<Layout[]>([])
const monitors = ref<MonitorInfo[]>([])
const selected = ref<string>('')
const monitor = ref<number>(0)
const busy = ref(false)
const outcome = ref<ApplyOutcome | null>(null)
const error = ref('')

const current = computed(() => layouts.value.find((l) => l.name === selected.value) || null)

/** 预览画布尺寸（保持 16:9，仅用于显示比例）。 */
const CANVAS = { w: 480, h: 270 }

function rectStyle(r: { x: number; y: number; w: number; h: number }) {
  return {
    left: `${r.x * 100}%`,
    top: `${r.y * 100}%`,
    width: `${r.w * 100}%`,
    height: `${r.h * 100}%`,
  }
}

/** AI 侧栏占位（预览里画出来，让"窗口不覆盖侧栏"可见）。 */
const sidebarStyle = computed(() => {
  const sb = current.value?.aiSidebar
  if (!sb?.enabled) return null
  const width = `${(sb.width || 0) * 100}%`
  return sb.edge === 'left' ? { left: '0', width } : { right: '0', width }
})

async function load() {
  try {
    layouts.value = await layoutApi.list()
    monitors.value = await layoutApi.monitors()
    if (!selected.value && layouts.value.length) {
      selected.value = layouts.value[0].name
      monitor.value = layouts.value[0].monitor ?? 0
    }
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(load)

function pick(l: Layout) {
  selected.value = l.name
  monitor.value = l.monitor ?? 0
  outcome.value = null
}

async function apply() {
  if (!selected.value) return
  busy.value = true
  error.value = ''
  outcome.value = null
  try {
    outcome.value = await layoutApi.apply(selected.value, monitor.value)
  } catch (err) {
    error.value = String(err)
  } finally {
    busy.value = false
  }
}

const statusText: Record<string, string> = {
  placed: '已排列',
  skipped_not_running: '未运行（跳过）',
  skipped_no_window: '无可见窗口（跳过）',
  failed: '失败',
}
</script>

<template>
  <section class="layout-view">
    <header class="lv-toolbar">
      <label>
        显示器
        <select v-model.number="monitor" class="lv-monitor">
          <option v-for="m in monitors" :key="m.index" :value="m.index">
            #{{ m.index }}{{ m.primary ? '（主）' : '' }} · {{ m.work_w }}×{{ m.work_h }}
          </option>
        </select>
      </label>
      <button type="button" class="primary lv-apply" :disabled="busy || !selected" @click="apply">
        {{ busy ? '应用中…' : '应用布局' }}
      </button>
      <span class="lv-hint">窗口被挪乱后，再点一次即可复位</span>
    </header>

    <p v-if="error" class="lv-error">{{ error }}</p>

    <div class="lv-body">
      <aside class="lv-list">
        <button
          v-for="l in layouts"
          :key="l.name"
          type="button"
          class="lv-item"
          :class="{ active: l.name === selected }"
          @click="pick(l)"
        >
          <span class="lv-item__name">{{ l.name }}</span>
          <span class="lv-item__desc">{{ l.description || `${l.slots.length} 个槽位` }}</span>
        </button>
      </aside>

      <main class="lv-main">
        <div
          v-if="current"
          class="lv-canvas"
          :style="{ width: CANVAS.w + 'px', height: CANVAS.h + 'px' }"
        >
          <div
            v-for="(slot, i) in current.slots"
            :key="i"
            class="lv-slot"
            :style="rectStyle(slot.rect)"
            :title="`z=${slot.z}`"
          >
            <span class="lv-slot__app">{{ slot.app }}</span>
            <span class="lv-slot__ratio">
              {{ Math.round(slot.rect.w * 100) }}% × {{ Math.round(slot.rect.h * 100) }}%
            </span>
          </div>
          <div v-if="sidebarStyle" class="lv-sidebar" :style="sidebarStyle">AI 侧栏</div>
        </div>
        <p v-else class="lv-hint">左侧选择一个布局查看预览</p>

        <div v-if="outcome" class="lv-outcome">
          <p class="lv-outcome__head">
            已应用「{{ outcome.layout }}」：排列 <b>{{ outcome.placed }}</b> ·
            跳过 <b>{{ outcome.skipped }}</b> · 失败 <b>{{ outcome.failed }}</b>
            （{{ outcome.took_ms }} ms<span v-if="outcome.degraded_monitor">；目标显示器不存在，已降级到主显示器</span>）
          </p>
          <ul class="lv-slots">
            <li v-for="(s, i) in outcome.slots" :key="i" :class="`is-${s.status}`">
              <span class="lv-slots__app">{{ s.app }}</span>
              <span class="lv-slots__status">{{ statusText[s.status] || s.status }}</span>
              <span v-if="s.reason" class="lv-slots__reason">{{ s.reason }}</span>
            </li>
          </ul>
        </div>
      </main>
    </div>
  </section>
</template>

<style scoped>
.layout-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
}

.lv-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.lv-toolbar label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.lv-hint {
  color: var(--text-dim);
  font-size: 12px;
}

.lv-error {
  color: var(--danger);
}

.lv-body {
  display: flex;
  gap: 16px;
  min-height: 0;
  flex: 1;
}

.lv-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 150px;
}

.lv-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  background: transparent;
  border-color: transparent;
  gap: 2px;
}

.lv-item.active {
  background: var(--accent-weak);
  border-color: var(--accent);
}

.lv-item__name {
  font-weight: 600;
}

.lv-item__desc {
  color: var(--text-dim);
  font-size: 12px;
}

.lv-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.lv-canvas {
  position: relative;
  background: var(--bg);
  border: 1px dashed var(--border);
  border-radius: 8px;
  flex: 0 0 auto;
}

.lv-slot {
  position: absolute;
  box-sizing: border-box;
  border: 1px solid var(--accent);
  background: var(--accent-weak);
  border-radius: 4px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.lv-slot__app {
  font-weight: 600;
  font-size: 12px;
}

.lv-slot__ratio {
  color: var(--text-dim);
  font-size: 11px;
}

.lv-sidebar {
  position: absolute;
  top: 0;
  bottom: 0;
  background: repeating-linear-gradient(
    45deg,
    var(--border),
    var(--border) 6px,
    transparent 6px,
    transparent 12px
  );
  border-left: 1px solid var(--border);
  display: grid;
  place-items: center;
  font-size: 12px;
  color: var(--text-dim);
}

.lv-outcome__head {
  font-size: 13px;
}

.lv-slots {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.lv-slots li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  padding: 3px 6px;
  border-radius: 4px;
  background: var(--panel);
  border: 1px solid var(--border);
}

.lv-slots li.is-placed {
  border-color: var(--ok);
}

.lv-slots li.is-failed {
  border-color: var(--danger);
}

.lv-slots__status {
  color: var(--text-dim);
}

.lv-slots__reason {
  color: var(--danger);
}
</style>
