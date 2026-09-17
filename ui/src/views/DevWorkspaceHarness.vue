<script setup lang="ts">
/**
 * TECH-02 · Workspace Runtime 验证固件（dev-only，挂 /dev/workspace，不进导航）。
 *
 * ## 它是干什么的
 * 本固件是 Workspace Runtime 的**唯一消费者**，也是一块"可机器断言的舞台"：
 * 它把 §一~§六 的每条能力都做成一个可见可点的面，`verify_tech02_workspace.py` 用
 * Edge 无头 + CDP 在这块舞台上跑 T1~T6。
 *
 * ## 铁律：只经 `workspaceRuntime` 取数/改数
 * 本文件**只 import `@/workspace/runtime`**，绝不 import `@/workspace/store` /
 * `@/workspace/layout`（数据源细节被门面挡住）。这条纪律是 T1 的静态判据之一：
 * 一旦页面绕过门面直连 store，UI 就又能"直接访问 mock"，改造的意义就没了。
 *
 * ## DOM 契约（`layout.ts` 依赖它）
 * ```
 * [data-wwr-canvas]              ← 坐标系原点
 *   └─ [data-app-id="<appId>"]   ← 应用窗口（绝对定位，left/top 即快照 x/y）
 * ```
 */
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import { workspaceRuntime } from '@/workspace/runtime'
import type { PrepareReport, WorkspaceApp } from '@/workspace/runtime'

// ---------------------------------------------------------------- 订阅 → 响应式
// store 是框架无关的（将来 TECH-03 复用），所以这里显式订阅、自己接进 Vue 响应式。
const rev = ref(0)
let unsubscribe: (() => void) | null = null
/** 上一次已同步进本地镜像的快照 id —— 只在"布局指向变了"时才重同步，避免拖拽被覆盖。 */
let lastSyncedSnapId: string | null = null

const current = computed(() => {
  void rev.value
  return workspaceRuntime.getCurrent()
})
const apps = computed<WorkspaceApp[]>(() => {
  void rev.value
  return workspaceRuntime.getApps()
})
const layout = computed(() => {
  void rev.value
  return workspaceRuntime.getLayout()
})
const templates = computed(() => {
  void rev.value
  return workspaceRuntime.listTemplates()
})
const snapshots = computed(() => {
  void rev.value
  return workspaceRuntime.listLayoutSnapshots()
})
const lastEvent = computed(() => {
  void rev.value
  return workspaceRuntime.lastWindowEvent()
})
const focused = computed(() => {
  void rev.value
  return workspaceRuntime.focusedWindowId()
})

onMounted(() => {
  unsubscribe = workspaceRuntime.subscribe(() => {
    rev.value += 1
    // 谁调用了 loadLayoutSnapshot（UI 按钮或外部/验收脚本）都要把本地镜像拉齐，
    // 否则 Vue 会用旧几何把 restore 写回的 DOM 再冲掉。
    const sid = workspaceRuntime.getLayout()?.snapshotId ?? null
    if (sid !== lastSyncedSnapId) {
      lastSyncedSnapId = sid
      if (sid) syncPositionsFromSnapshot(sid)
    }
    // 无论哪条路径，最后都让 DOM 与镜像对齐（DOM 赢，见 adoptDomIntoPositions）。
    adoptDomIntoPositions()
    void nextTick(paintGeometry)
    log(`store rev=${workspaceRuntime.getRevision()}`)
  })
  // 首次进入若无工作空间，自动准备一个种子模板 —— 让舞台非空（不影响显式调用）。
  if (!workspaceRuntime.getCurrent()) {
    const first = workspaceRuntime.listTemplates()[0]
    if (first) void doPrepare(first.id)
  }
})

onUnmounted(() => {
  unsubscribe?.()
  unsubscribe = null
})

// ---------------------------------------------------------------- 几何
// **DOM 是几何的唯一真相**（`layout.ts` 的快照就是读 DOM 的）。
// 因此这里**不用 `:style` 绑定**几何 —— 一旦交给 Vue 托管，`loadLayoutSnapshot()`
// 写回的 DOM 会在下一次 re-render 时被 Vue 用旧值冲掉（restore 静默失效）。
// 改为：`positions` 只作镜像，几何一律**命令式**写进 DOM（`paintGeometry`）。
interface Box {
  x: number
  y: number
  w: number
  h: number
  z: number
}
const positions = reactive<Record<string, Box>>({})
const GAP = 16
const PAD = 16
const W = 300
const H = 190
let zTop = 1

/** 为新出现的 app 铺默认几何（左上起按两列排）。 */
function ensurePositions(list: WorkspaceApp[]): void {
  list.forEach((a, i) => {
    if (!positions[a.appId]) {
      positions[a.appId] = {
        x: PAD + (i % 2) * (W + GAP),
        y: PAD + Math.floor(i / 2) * (H + GAP),
        w: W,
        h: H,
        z: ++zTop,
      }
    }
  })
}

/** 把快照几何灌进镜像（restore / loadTemplate / prepare 后调用）。 */
function syncPositionsFromSnapshot(snapshotId: string | null): void {
  if (!snapshotId) return
  const snap = workspaceRuntime.getLayoutSnapshot(snapshotId)
  if (!snap) return
  for (const e of snap.entries) {
    positions[e.appId] = { x: e.x, y: e.y, w: e.width, h: e.height, z: e.zIndex }
  }
}

function elOf(appId: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-wwr-canvas] [data-app-id="${appId}"]`)
}

function writeBox(el: HTMLElement, b: Box): void {
  el.style.left = `${b.x}px`
  el.style.top = `${b.y}px`
  el.style.width = `${b.w}px`
  el.style.height = `${b.h}px`
  el.style.zIndex = String(b.z)
}

/** 把镜像几何重放到 DOM。放在 `nextTick` 里调用，保证 Vue 已把窗口元素渲染出来。 */
function paintGeometry(): void {
  for (const [appId, b] of Object.entries(positions)) {
    const el = elOf(appId)
    if (el) writeBox(el, b)
  }
}

/**
 * 「DOM 赢」：把窗口的**当前真实 DOM 几何**收回镜像。
 *
 * 为什么需要：`loadLayoutSnapshot()`（UI 按钮或外部/验收脚本）会直接写 DOM
 * （`applyLayoutToDom`），此时镜像落后于 DOM。虽然几何以 DOM 为准、显示没问题，
 * 但镜像一旦落后，下一次 `paintGeometry()` 就会把旧值又写回去 —— 所以这里兜底拉齐。
 * 未落盘的窗口（无 inline width）跳过，避免把"还没画过"的收缩宽度收进镜像。
 */
function adoptDomIntoPositions(): void {
  const canvas = document.querySelector<HTMLElement>('[data-wwr-canvas]')
  if (!canvas) return
  const cr = canvas.getBoundingClientRect()
  const ox = cr.left + canvas.clientLeft
  const oy = cr.top + canvas.clientTop
  for (const el of Array.from(canvas.querySelectorAll<HTMLElement>('[data-app-id]'))) {
    const appId = el.dataset.appId
    if (!appId || !el.style.width) continue
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1) continue
    const z = Number.parseInt(getComputedStyle(el).zIndex, 10)
    positions[appId] = {
      x: Math.round(r.left - ox),
      y: Math.round(r.top - oy),
      w: Math.round(r.width),
      h: Math.round(r.height),
      z: Number.isFinite(z) ? z : (positions[appId]?.z ?? 1),
    }
  }
}

// app 列表变化时补齐几何并落盘到 DOM（watch 而非带副作用的 computed）。
watch(
  () => apps.value.map((a) => a.appId).join('|'),
  () => {
    ensurePositions(apps.value)
    void nextTick(paintGeometry)
  },
  { immediate: true },
)

// ---------------------------------------------------------------- 拖拽
// 坐标基准必须与 `layout.ts` 的快照基准一致：窗口矩形相对 canvas **内容盒**左上角。
let dragging: { appId: string; dx: number; dy: number; ox: number; oy: number } | null = null

function canvasOrigin(): { x: number; y: number } {
  const canvas = document.querySelector<HTMLElement>('[data-wwr-canvas]')
  if (!canvas) return { x: 0, y: 0 }
  const r = canvas.getBoundingClientRect()
  return { x: r.left + canvas.clientLeft, y: r.top + canvas.clientTop }
}

function startDrag(appId: string, ev: PointerEvent): void {
  const b = positions[appId]
  if (!b) return
  const el = (ev.currentTarget as HTMLElement | null)?.closest<HTMLElement>('[data-app-id]')
  const rect = el?.getBoundingClientRect()
  const o = canvasOrigin()
  dragging = {
    appId,
    dx: ev.clientX - (rect?.left ?? o.x + b.x),
    dy: ev.clientY - (rect?.top ?? o.y + b.y),
    ox: o.x,
    oy: o.y,
  }
  bringToFront(appId)
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', stopDrag)
}

function onDragMove(ev: PointerEvent): void {
  if (!dragging) return
  const b = positions[dragging.appId]
  if (!b) return
  b.x = Math.max(0, Math.round(ev.clientX - dragging.dx - dragging.ox))
  b.y = Math.max(0, Math.round(ev.clientY - dragging.dy - dragging.oy))
  const el = elOf(dragging.appId)
  if (el) writeBox(el, b)   // 命令式落盘（几何不交给 Vue）
}

function stopDrag(): void {
  dragging = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', stopDrag)
}

function bringToFront(appId: string): void {
  const b = positions[appId]
  if (!b) return
  b.z = ++zTop
  const el = elOf(appId)
  if (el) el.style.zIndex = String(b.z)
}

// ---------------------------------------------------------------- 操作
const busy = ref(false)
const report = ref<PrepareReport | null>(null)
const logs = ref<string[]>([])

function log(msg: string): void {
  const t = new Date().toLocaleTimeString()
  logs.value = [...logs.value.slice(-199), `${t} ${msg}`]
}

async function doPrepare(id: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  log(`prepare → ${id}`)
  try {
    // 故意给一点步进时延，让"真异步流水线"在 UI 上也看得见。
    const r = await workspaceRuntime.prepareWorkspace(id, {
      stepDelayMs: 40,
      onProgress: (s) => log(`  step ${s.step} · ${s.ok ? 'ok' : 'FAIL'} · ${s.detail}`),
    })
    report.value = r
    syncPositionsFromSnapshot(r.usedSnapshotId)
    void nextTick(paintGeometry)
    log(`prepare done ok=${r.ok} snapshot=${r.usedSnapshotId ?? 'none'} ${Math.round(r.ms)}ms`)
  } finally {
    busy.value = false
  }
}

function onSaveLayout(): void {
  const snap = workspaceRuntime.saveLayoutSnapshot()
  log(snap ? `save layout → ${snap.snapshotId}（${snap.entries.length} 条）` : 'save layout 失败（无画布/无窗口）')
}

function onRestoreLayout(): void {
  const list = workspaceRuntime.listLayoutSnapshots()
  const last = list[list.length - 1]
  if (!last) {
    log('没有可恢复的快照')
    return
  }
  const snap = workspaceRuntime.loadLayoutSnapshot(last.snapshotId)
  syncPositionsFromSnapshot(snap?.snapshotId ?? null)
  void nextTick(paintGeometry)
  log(snap ? `restore layout ← ${snap.snapshotId}` : `restore 失败：${last.snapshotId}`)
}

function onClearLayout(): void {
  const n = workspaceRuntime.clearLayoutSnapshot()
  // DOM 复位由 UI 负责：回到默认排布。
  zTop = 0
  for (const k of Object.keys(positions)) delete positions[k]
  ensurePositions(apps.value)
  void nextTick(paintGeometry)
  log(`clear layout：清除 ${n} 个快照，回到 auto`)
}

function onCreateTemplate(): void {
  const name = window.prompt('模板名称', `模板 ${templates.value.length + 1}`)
  if (!name) return
  try {
    const tpl = workspaceRuntime.createTemplate({ name })
    log(`create template → ${tpl.id}「${tpl.name}」快照=${tpl.layoutSnapshot ? 'yes' : 'no'}`)
  } catch (err) {
    log(`create template 失败：${String(err)}`)
  }
}

function onSaveTemplate(): void {
  const tpl = workspaceRuntime.saveTemplate()
  log(tpl ? `save template → ${tpl.id}「${tpl.name}」` : 'save template 失败（无工作空间）')
}

function onLoadTemplate(id: string): void {
  const tpl = workspaceRuntime.loadTemplate(id)
  if (!tpl) {
    log(`load template 失败：${id}`)
    return
  }
  syncPositionsFromSnapshot(tpl.layoutSnapshot?.snapshotId ?? null)
  void nextTick(paintGeometry)
  log(`load template ← ${tpl.id}「${tpl.name}」`)
}

function onStatus(appId: string, status: 'running' | 'waiting' | 'closed'): void {
  const app = workspaceRuntime.updateStatus(appId, status)
  log(app ? `updateStatus ${appId} → ${app.status}` : `updateStatus ${appId} 失败`)
}

function onWindowEvent(windowId: string, event: 'open' | 'close' | 'focus'): void {
  if (event === 'focus') {
    const appId = windowId.replace(/^win-/, '')
    if (positions[appId]) bringToFront(appId)
  }
  const app = workspaceRuntime.windowEvent({ windowId, event })
  log(app ? `windowEvent ${event} ${windowId} → ${app.status}` : `windowEvent ${event} ${windowId} 未匹配`)
}
</script>

<template>
  <section class="dwh-root" data-wwr-harness>
    <header class="dwh-head">
      <h3>Workspace Runtime 验证固件（dev-only）</h3>
      <span class="dwh-hint">
        当前：{{ current ? `${current.name}（${current.workspaceId}）` : '无工作空间' }}
        · layout={{ layout?.type ?? '-' }}{{ layout?.snapshotId ? `:${layout.snapshotId}` : '' }}
        · rev={{ rev }}
      </span>
    </header>

    <div class="dwh-grid">
      <!-- 左：模板 / 快照 / 报告 -->
      <aside class="dwh-side">
        <div class="dwh-card">
          <div class="dwh-card-title">模板（§四）</div>
          <ul class="dwh-list" data-wwr-templates>
            <li v-for="t in templates" :key="t.id" :data-tpl-id="t.id">
              <button type="button" class="dwh-tpl" @click="doPrepare(t.id)">
                准备「{{ t.name }}」
              </button>
              <button type="button" class="dwh-mini" @click="onLoadTemplate(t.id)">加载</button>
              <span class="dwh-meta">{{ t.apps.length }} app · 快照{{ t.layoutSnapshot ? '✓' : '✗' }}</span>
            </li>
          </ul>
          <div class="dwh-row">
            <button type="button" data-wwr-create-tpl @click="onCreateTemplate">创建模板</button>
            <button type="button" data-wwr-save-tpl @click="onSaveTemplate">保存为模板</button>
          </div>
        </div>

        <div class="dwh-card">
          <div class="dwh-card-title">布局快照（§三）</div>
          <div class="dwh-row">
            <button type="button" data-wwr-save-layout @click="onSaveLayout">保存布局</button>
            <button type="button" data-wwr-restore-layout @click="onRestoreLayout">恢复布局</button>
            <button type="button" data-wwr-clear-layout @click="onClearLayout">清除</button>
          </div>
          <ul class="dwh-list">
            <li v-for="s in snapshots" :key="s.snapshotId" :data-snap-id="s.snapshotId">
              {{ s.snapshotId }} · {{ s.entries.length }} 条
            </li>
          </ul>
        </div>

        <div class="dwh-card">
          <div class="dwh-card-title">准备流水线（§六）</div>
          <ol class="dwh-steps" data-wwr-steps>
            <li v-for="(s, i) in report?.steps ?? []" :key="i" :data-step="s.step">
              {{ s.step }} — {{ s.ok ? 'ok' : 'FAIL' }} · {{ s.detail }}
            </li>
            <li v-if="!report" class="dwh-meta">（尚未准备）</li>
          </ol>
        </div>
      </aside>

      <!-- 右：画布 -->
      <div class="dwh-stage">
        <div class="dwh-toolbar">
          <span class="dwh-meta">焦点：{{ focused ?? '-' }}</span>
          <span class="dwh-meta" data-wwr-last-event>
            最近事件：{{ lastEvent ? `${lastEvent.event} ${lastEvent.windowId}` : '-' }}
          </span>
          <span class="dwh-meta">app {{ apps.length }}</span>
        </div>

        <div class="dwh-canvas" data-wwr-canvas>
          <div
            v-for="app in apps"
            :key="app.appId"
            class="dwh-window"
            :class="`dwh-st-${app.status}`"
            :data-app-id="app.appId"
            :data-status="app.status"
          >
            <div class="dwh-window-bar" @pointerdown="startDrag(app.appId, $event)">
              <span class="dwh-window-title">{{ app.name }}</span>
              <span class="dwh-badge" :data-wwr-status="app.appId">{{ app.status }}</span>
            </div>
            <div class="dwh-window-body">
              <div class="dwh-meta">windowId: {{ app.windowId ?? '-' }}</div>
              <div class="dwh-meta">layoutNode: {{ app.layoutNode ?? '-' }}</div>
              <div class="dwh-row">
                <button type="button" :data-wwr-open="app.appId" @click="onWindowEvent(app.windowId ?? `win-${app.appId}`, 'open')">open</button>
                <button type="button" :data-wwr-focus="app.appId" @click="onWindowEvent(app.windowId ?? `win-${app.appId}`, 'focus')">focus</button>
                <button type="button" :data-wwr-close="app.appId" @click="onWindowEvent(app.windowId ?? `win-${app.appId}`, 'close')">close</button>
              </div>
              <div class="dwh-row">
                <button type="button" :data-wwr-st-running="app.appId" @click="onStatus(app.appId, 'running')">running</button>
                <button type="button" :data-wwr-st-waiting="app.appId" @click="onStatus(app.appId, 'waiting')">waiting</button>
                <button type="button" :data-wwr-st-closed="app.appId" @click="onStatus(app.appId, 'closed')">closed</button>
              </div>
            </div>
          </div>
          <p v-if="!apps.length" class="dwh-empty">没有应用 —— 先「准备」一个模板。</p>
        </div>

        <div class="dwh-log" data-wwr-log>
          <div v-for="(l, i) in logs" :key="i" class="dwh-log-line">{{ l }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dwh-root {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.dwh-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  align-items: baseline;
}
.dwh-head h3 {
  margin: 0;
  font-size: 15px;
}
.dwh-hint,
.dwh-meta {
  color: var(--text-3);
  font-size: 12px;
}
.dwh-grid {
  display: grid;
  /* 宽屏左窄右宽；窄屏自动堆叠 —— T6 断点友好 */
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
@media (max-width: 900px) {
  .dwh-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
.dwh-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.dwh-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  background: var(--surface-1);
  padding: 10px;
}
.dwh-card-title {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 8px;
}
.dwh-list {
  margin: 0 0 8px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dwh-list li {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: var(--text-2);
}
.dwh-steps {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-2);
}
.dwh-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
button {
  font: inherit;
  font-size: 12px;
  padding: 2px 8px;
  color: var(--text-1);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  cursor: pointer;
}
button:hover {
  background: var(--surface-3, var(--surface-2));
}
.dwh-mini {
  padding: 2px 6px;
  font-size: 11px;
}
.dwh-stage {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.dwh-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.dwh-canvas {
  position: relative;
  min-height: 420px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  background: var(--surface-1);
}
.dwh-window {
  position: absolute;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  background: var(--surface-2);
  overflow: hidden;
}
.dwh-window-bar {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 8px;
  cursor: move;
  background: var(--surface-3, var(--surface-2));
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-1);
  user-select: none;
}
.dwh-window-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 8px;
}
.dwh-badge {
  font-size: 11px;
  color: var(--text-3);
}
.dwh-st-closed {
  opacity: 0.45;
}
.dwh-empty {
  padding: 12px;
  color: var(--text-3);
  font-size: 12px;
}
.dwh-log {
  height: 160px;
  overflow-y: auto;
  /* S2 判据纯粹化：关掉 scroll anchoring（见 DevMotionHarness 同款说明）。 */
  overflow-anchor: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  background: var(--surface-1);
  padding: 6px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--text-2);
}
.dwh-log-line {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
