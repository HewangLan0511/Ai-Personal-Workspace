<script setup lang="ts">
/**
 * RunView —— 工作模式沉浸页 UI 壳（TECH-07-C Phase C1）
 *
 * ## 原型对照（personal-workspace-ui `#/run`）
 * run-head（返回/emoji/名称/工作中徽章/布局 seg/排列 seg/时钟）
 * + 状态栏（当前任务 / 应用三态 chips / 布局 / 模式）
 * + appbar（软件标签页 + AI 标签）
 * + minimap（真实窗口投影）+ 主工作区域（窗口舞台画布）。
 *
 * ## C2 变更（Observe 接线：只换数据源，不动布局/视觉/token/动画）
 * - 数据消费 adapter 投影事实：RunWindowFacts / RunAppFacts / RunModeFacts
 *   —— core 原始结构（WindowInfo/SlotResult）与 command 名不出 adapter；
 * - 应用 chips / appbar 标签从「应用 #id」变为真实软件名 + runState 三态点
 *   （pw-dot--ok/wait/off 既有原语，零新 token）；
 * - 空态 / 未连接态如实展示（connectivity: connected/degraded/offline），
 *   不删任何 UI 区域、不伪造窗口；
 * - 拖拽 / 摆窗：仍然零（窗口矩形 pointer-events:none，无 drag 事件 → 无
 *   windows_place 路径；窗口控制属 C3）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

// 注意：必须用 `/index` 子路径——裸 `@/workspace/runtime` 会被 TS 解析到
// 同名的门面文件 runtime.ts（TECH-02 冻结域），而不是本 adapter 目录。
// 子路径写法同时保持 verify_tech02 T1c 的 `workspace/runtime` 精确匹配门禁不被误触。
// C7-B：MIN_NORM/SNAP_NORM 从 adapter 导入（单一来源），RunView 不再私有定义魔法数。
import { MIN_NORM, SNAP_NORM, workspaceAdapter } from '@/workspace/runtime/index'
import type { WorkspaceFacts } from '@/workspace/runtime/facts'
import type { PlacementResult } from '@/workspace/runtime/actions'
import type { SnapshotStatus } from '@/workspace/runtime/snapshot'
import type { LayoutApplyOutcome, LayoutSaveOutcome } from '@/workspace/runtime/layout'
import { useAiStore } from '@/stores/ai'

const router = useRouter()
const ai = useAiStore()

const facts = ref<WorkspaceFacts | null>(null)
const loadError = ref('')
const clock = ref(clockText())
let timer: number | null = null

function clockText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

const modeName = computed(() => facts.value?.mode?.running ?? '')
const modeMeta = computed(() => {
  const name = modeName.value
  if (!name || !facts.value) return null
  return facts.value.modes.find((m) => m.name === name) ?? null
})

/** 当前模式拉起的软件投影（appbar 标签 + 状态栏 chips 的数据源，C2）。 */
const modeApps = computed(() => facts.value?.mode.apps ?? [])

/** 模式描述（投影字段；C1 走 modeMeta.description，C2 走聚合投影）。 */
const modeDesc = computed(() => facts.value?.mode.description ?? '')

/** 布局名（当前模式绑定的布局）。 */
const layoutName = computed(() => facts.value?.mode.layout ?? '')

/** 连接态：offline = 事实拉取全失败（如实"未连接"，不伪造数据）。 */
const connectivity = computed(() => facts.value?.connectivity ?? 'offline')

/** 可管理窗口总数（观察口径，来自 windows facts 本身）。 */
const windowCount = computed(() => facts.value?.windows.length ?? 0)

/** runState → 既有 pw-dot 变体（零新 token：ok=运行中 wait=启动中 off=其余）。 */
function dotOf(runState: string): string {
  if (runState === 'running') return 'pw-dot--ok'
  if (runState === 'launching') return 'pw-dot--wait'
  return 'pw-dot--off'
}
const runStateText: Record<string, string> = {
  running: '运行中',
  launching: '启动中',
  failed: '启动失败',
  skipped: '已跳过',
  unknown: '状态未知',
}

/** 主显示器工作区（minimap / 舞台投影的归一化基准）。 */
const work = computed(() => {
  const mons = facts.value?.monitors ?? []
  const primary = mons.find((m) => m.primary) ?? mons[0]
  if (!primary) return null
  return { x: primary.work_x, y: primary.work_y, w: primary.work_w, h: primary.work_h }
})

/**
 * C7-E 卡片归属证据：pid → 软件名。**只认 mode_progress.slots 的登记证据**
 * （slots 是唯一同时带 app/appId/pid 的证据链），无证据不标 —— 禁止按标题/
 * exe 猜归属（与 projection.ts 归属判据同一纪律）。
 */
const pidAppName = computed(() => {
  const m = new Map<number, string>()
  for (const s of facts.value?.progress?.slots ?? []) {
    if (typeof s.pid === 'number' && s.pid > 0) {
      const name = s.app || (s.appId !== null ? `应用 #${s.appId}` : '')
      if (name) m.set(s.pid, name)
    }
  }
  return m
})

/** 真实窗口在工作区内的归一化投影（minimap + 舞台共用一份几何；最小化不投影）。 */
const projections = computed(() => {
  const base = work.value
  const wins = facts.value?.windows ?? []
  if (!base || base.w <= 0 || base.h <= 0) return []
  return wins
    .filter((w) => w.rect && w.state !== 'minimized')
    .map((w) => {
      const r = w.rect!
      const x = Math.max(0, (r.x - base.x) / base.w)
      const y = Math.max(0, (r.y - base.y) / base.h)
      const wRatio = Math.min(1, r.w / base.w)
      const hRatio = Math.min(1, r.h / base.h)
      return {
        hwnd: w.hwnd,
        title: w.title,
        mode: w.belongsToMode,
        state: w.state,
        app: pidAppName.value.get(w.pid) ?? null,
        x,
        y,
        w: wRatio,
        h: hRatio,
      }
    })
    .filter((p) => p.x < 1 && p.y < 1 && p.w > MIN_NORM && p.h > MIN_NORM)
})

/**
 * C7-E 卡片条文案：标题（前缀，保持既有 includes 断言兼容）+ 归属证据
 * `app:<名>`（仅 slots pid 证据，无证据不标）+ 窗口状态（最大化/最小化）
 * + 只读标识（非当前模式窗口）。不引入 drawer、不猜 exe、不伪造"未知"类。
 */
function winBarText(p: {
  title: string
  mode: boolean
  app: string | null
  state: string
}): string {
  const bits: string[] = [p.title || '窗口']
  if (p.app) bits.push(`app:${p.app}`)
  if (p.state === 'maximized') bits.push('最大化')
  else if (p.state === 'minimized') bits.push('最小化')
  if (!p.mode) bits.push('只读')
  return bits.join(' · ')
}

async function refresh(): Promise<void> {
  // C3：交互（拖拽/缩放）进行中跳过轮询覆盖 —— 本地预览是用户意图，事实以 commit 后为准
  if (interaction !== null) return
  try {
    const snap = await workspaceAdapter.snapshot()
    facts.value = snap
    // C3 closure audit：core 不可达时**作废上一次摆位结果** —— 断连后继续展示
    // "✓ 已摆位"就是陈旧成功（= 假成功）；未连接态由 hint 区如实表达。
    if (snap.connectivity === 'offline') placement.value = null
    loadError.value = snap.failures.length ? `部分事实不可用：${snap.failures.join(' / ')}` : ''
  } catch (e) {
    loadError.value = String((e as Error)?.message ?? e)
  }
}

// ================================================================ C3 摆位交互
// 设计（TECH-07-C3 §6/§8/§9）：
// - pointermove 只做**本地预览**（命令式写 style，不进 Vue 响应式、不触发渲染风暴）；
// - commit 边界 = pointerup，一次交互恰好一次 windows_place（无 RPC 风暴）；
// - 坐标换算在 adapter（placeWindow）内：RunView 只产出归一化意图；
// - 成功与否都等 facts 确认（成功 → refresh 对齐事实；失败 → refresh 回滚预览 +
//   保持明确失败状态），绝不把本地几何当成"窗口已移动"。

interface Interaction {
  hwnd: number
  mode: 'move' | 'resize'
  dir: string | null
  /** 归一化起始几何 */
  start: { x: number; y: number; w: number; h: number }
  /** pointer 起点与 stage 几何（CSS px） */
  px: number
  py: number
  stage: { left: number; top: number; w: number; h: number }
  /** 预览目标元素（命令式写 style） */
  el: HTMLElement
}

let interaction: Interaction | null = null
const placement = ref<PlacementResult | null>(null)

function stageEl(): HTMLElement | null {
  return document.querySelector('[data-pw="run-stage"]')
}

function beginInteraction(
  ev: PointerEvent,
  hwnd: number,
  mode: 'move' | 'resize',
  dir: string | null,
): void {
  const el = (ev.currentTarget as HTMLElement).closest<HTMLElement>('.run-win')
  const st = stageEl()
  if (!el || !st) return
  const p = projections.value.find((q) => q.hwnd === hwnd)
  if (!p) return
  // 上一次交互若异常残留（没收到 up/cancel），先清理再开始，避免状态叠加
  cancelInteraction()
  const r = st.getBoundingClientRect()
  interaction = {
    hwnd,
    mode,
    dir,
    start: { x: p.x, y: p.y, w: p.w, h: p.h },
    px: ev.clientX,
    py: ev.clientY,
    stage: { left: r.left, top: r.top, w: r.width, h: r.height },
    el,
  }
  // 指针捕获只是跟手增强（指针离开元素也能收 move）；对合成/已释放的 pointerId
  // 会抛 NotFoundError —— 捕获失败不能拖死整条交互链（move/up 监听在后面必须挂上）。
  try {
    el.setPointerCapture(ev.pointerId)
  } catch {
    /* 无活动指针（合成事件 / 已释放）——window 级监听仍可完成拖拽 */
  }
  window.addEventListener('pointermove', onInteractMove)
  window.addEventListener('pointerup', commitInteraction)
  // 异常路径（系统取消手势 / 指针捕获丢失）：只清理、不提交，绝不发起摆位
  window.addEventListener('pointercancel', cancelInteraction)
  window.addEventListener('lostpointercapture', cancelInteraction)
  // C7-C Esc 链：交互进行中按 Esc = 用户撤销，与 pointercancel 同一取消语义
  window.addEventListener('keydown', onInteractKey)
}

/**
 * C7-C Esc 取消：交互进行中按 Escape → cancelInteraction（不调用 windows_place、
 * 不产生任何 core 请求、不修改事实层，预览写回起始几何）。仅交互存在时消费该按键。
 */
function onInteractKey(ev: KeyboardEvent): void {
  if (!interaction || ev.key !== 'Escape') return
  ev.preventDefault()
  cancelInteraction()
}

function startDrag(ev: PointerEvent, hwnd: number): void {
  beginInteraction(ev, hwnd, 'move', null)
}

function startResize(ev: PointerEvent, hwnd: number, dir: string): void {
  ev.stopPropagation()
  beginInteraction(ev, hwnd, 'resize', dir)
}

/** 写几何到投影元素（命令式，预览与回滚共用同一处写入）。 */
function writeGeometry(
  el: HTMLElement,
  g: { x: number; y: number; w: number; h: number },
): void {
  el.style.left = `${(g.x * 100).toFixed(2)}%`
  el.style.top = `${(g.y * 100).toFixed(2)}%`
  el.style.width = `${(g.w * 100).toFixed(2)}%`
  el.style.height = `${(g.h * 100).toFixed(2)}%`
}

/** 移除全部交互监听（move/up/cancel/capture-lost/keydown，与 begin 对称）。 */
function detachInteraction(): void {
  window.removeEventListener('pointermove', onInteractMove)
  window.removeEventListener('pointerup', commitInteraction)
  window.removeEventListener('pointercancel', cancelInteraction)
  window.removeEventListener('lostpointercapture', cancelInteraction)
  window.removeEventListener('keydown', onInteractKey)
}

/** 预览几何计算：pointer delta（CSS px）→ 归一化 delta → 应用于起始几何。 */
const lastMove = { x: 0, y: 0 }

function previewGeometry(it: Interaction): { x: number; y: number; w: number; h: number } {
  const dx = (lastMove.x - it.px) / it.stage.w
  const dy = (lastMove.y - it.py) / it.stage.h
  const s = it.start
  let { x, y, w, h } = s
  if (it.mode === 'move') {
    x = s.x + dx
    y = s.y + dy
  } else {
    const d = it.dir ?? ''
    if (d.includes('e')) w = Math.max(MIN_NORM, s.w + dx)
    if (d.includes('s')) h = Math.max(MIN_NORM, s.h + dy)
    if (d.includes('w')) {
      w = Math.max(MIN_NORM, s.w - dx)
      x = s.x + (s.w - w)
    }
    if (d.includes('n')) {
      h = Math.max(MIN_NORM, s.h - dy)
      y = s.y + (s.h - h)
    }
  }
  // C7-A 预览侧同口径收口（C5-06）：w/h 与 x/y 联合约束 —— 预览不再展示 x+w>1
  // 的越界形态；commit 端 adapter placeWindow 已做同规则联合校验（两端一致）。
  w = Math.min(Math.max(w, MIN_NORM), 1)
  h = Math.min(Math.max(h, MIN_NORM), 1)
  x = Math.min(Math.max(x, 0), 1 - w)
  y = Math.min(Math.max(y, 0), 1 - h)
  // C7-D 吸附：仅作用于本预览层（贴近工作区四缘 ≤ SNAP_NORM 时吸上去）。
  // commit 语义不变：仍单次 windows_place，adapter 收到的是吸附后的合法意图，
  // 不新增任何 core 请求、不改 facts。
  if (Math.abs(x) <= SNAP_NORM) x = 0
  else if (Math.abs(x + w - 1) <= SNAP_NORM) x = 1 - w
  if (Math.abs(y) <= SNAP_NORM) y = 0
  else if (Math.abs(y + h - 1) <= SNAP_NORM) y = 1 - h
  return { x, y, w, h }
}

function onInteractMove(ev: PointerEvent): void {
  const it = interaction
  if (!it) return
  lastMove.x = ev.clientX
  lastMove.y = ev.clientY
  const g = previewGeometry(it)
  if (!g) return
  // 命令式预览（跟手），不经过 Vue 响应式 —— 每帧只有 style 写入
  writeGeometry(it.el, g)
}

/**
 * 交互取消（pointercancel / lostpointercapture）：清理状态 + 监听，
 * **不发起任何摆位**（取消 ≠ 用户确认），预览写回起始几何。
 */
function cancelInteraction(): void {
  const it = interaction
  interaction = null
  detachInteraction()
  if (!it) return
  writeGeometry(it.el, it.start)
}

async function commitInteraction(): Promise<void> {
  const it = interaction
  interaction = null
  detachInteraction()
  if (!it) return
  const g = previewGeometry(it)
  it.el.style.zIndex = ''
  if (!g) return
  const work = workAreaPx()
  if (!work) {
    placement.value = { status: 'failed', hwnd: it.hwnd, message: '主显示器工作区不可用' }
    writeGeometry(it.el, it.start)
    await refresh()
    return
  }
  // 归一化意图 → adapter（段位/归属校验 + 物理像素换算 + windows_place）
  const result = await workspaceAdapter.actions.placeWindow(
    { hwnd: it.hwnd, x: g.x, y: g.y, w: g.w, h: g.h },
    work,
  )
  placement.value = result
  // 事实确认：成功 → 等 facts 对齐真实几何；非 placed → 预览只是本地意图，
  // 必须写回起始几何（Vue :style 绑定值未变时不会重绘，否则"请求几何"会
  // 滞留成"已确认几何"）—— 绝不以本地几何为准。
  if (result.status !== 'placed') writeGeometry(it.el, it.start)
  await refresh()
}

/** 主显示器工作区（物理像素，adapter 坐标换算的输入）。 */
function workAreaPx(): { x: number; y: number; w: number; h: number } | null {
  const mons = facts.value?.monitors ?? []
  const primary = mons.find((m) => m.primary) ?? mons[0]
  if (!primary) return null
  return { x: primary.work_x, y: primary.work_y, w: primary.work_w, h: primary.work_h }
}

// ================================================================ C5 布局（最小暴露）
// 「保存布局」= 受管窗口排布 → db_layout_upsert（模板语义，slot 只存 apps.name + 归一化 rect）；
// 「恢复默认」= 模式绑定布局 → layout_apply（core skip 语义原样透出：未运行跳过、不自动启动、
// 不激活焦点）。与 C4 快照双轨并存：本组入口不读写 workspace.snapshot.last。
// 视觉零新增：复用 pw-btn/pw-chip，无新 token / 动画 / 硬编码色。
const layoutBusy = ref(false)
const layoutChip = ref('')
const layoutDetail = ref('')

async function onLayoutSave(): Promise<void> {
  if (layoutBusy.value) return
  layoutBusy.value = true
  layoutChip.value = ''
  layoutDetail.value = ''
  try {
    const out: LayoutSaveOutcome = await workspaceAdapter.layout.save(modeName.value || '')
    if (out.status === 'saved') {
      layoutChip.value = `✓ 布局已保存 · ${out.name ?? ''}`
      layoutDetail.value = out.detail
    } else {
      layoutChip.value = '✕ 保存失败'
      layoutDetail.value = out.detail
    }
  } catch (e) {
    layoutChip.value = '✕ 保存失败'
    layoutDetail.value = String((e as Error)?.message ?? e)
  } finally {
    layoutBusy.value = false
    void refresh()
  }
}

async function onLayoutApply(): Promise<void> {
  if (layoutBusy.value) return
  layoutBusy.value = true
  layoutChip.value = ''
  layoutDetail.value = ''
  try {
    const out: LayoutApplyOutcome = await workspaceAdapter.layout.apply()
    const total = out.placed + out.skipped + out.failed
    switch (out.status) {
      case 'done':
        layoutChip.value = `✓ 布局已应用 ${out.placed} 个窗口`
        break
      case 'partial': {
        const skips = out.slots
          .filter((s) => s.status.startsWith('skipped'))
          .map((s) => `${s.app}:${s.status === 'skipped_not_running' ? '未运行' : '无窗口'}`)
        layoutChip.value = `◐ 布局部分应用 ${out.placed}/${total} · 跳过 ${out.skipped}${
          skips.length ? `（${skips.join('、')}）` : ''
        }`
        break
      }
      case 'offline':
        layoutChip.value = '✕ 未连接 —— 应用未执行'
        break
      case 'no_layout':
        layoutChip.value = '未绑定布局'
        break
      default:
        layoutChip.value = '✕ 应用失败'
    }
    layoutDetail.value = out.detail
  } catch (e) {
    layoutChip.value = '✕ 应用失败'
    layoutDetail.value = String((e as Error)?.message ?? e)
  } finally {
    layoutBusy.value = false
    void refresh()
  }
}

// ================================================================ C4 快照（最小暴露）
// 只做状态投影：两个既有按钮 + 一个既有 chip；结果文案如实映射 adapter 的
// 状态与 skip 原因（不把失败压成一句"恢复失败"）。视觉零新增（复用 pw-btn/pw-chip）。
const snapBusy = ref(false)
const snapStatus = ref<SnapshotStatus | null>(null)
const snapResult = ref('')

const snapshotText = computed(() => {
  const r = snapResult.value
  if (r) return r
  const s = snapStatus.value
  if (!s) return '快照：未知'
  if (!s.has) return '快照：无'
  if (!s.valid) return '快照：已损坏（保留原值）'
  return `快照：${s.managed} 个窗口 · ${s.sameRun ? '同一运行期' : '跨重启'}`
})

async function refreshSnapStatus(): Promise<void> {
  try {
    snapStatus.value = await workspaceAdapter.windowSnapshot.status()
  } catch {
    snapStatus.value = null
  }
}

async function onSnapshotSave(): Promise<void> {
  snapBusy.value = true
  snapResult.value = ''
  try {
    const out = await workspaceAdapter.windowSnapshot.capture()
    snapResult.value =
      out.status === 'saved'
        ? `快照：已保存 ${out.managed} 个窗口`
        : `快照：未保存（${out.status}）`
    await refreshSnapStatus()
  } catch (e) {
    snapResult.value = `快照：保存失败（${String((e as Error)?.message ?? e)}）`
  } finally {
    snapBusy.value = false
    void refresh()
  }
}

async function onSnapshotRestore(): Promise<void> {
  snapBusy.value = true
  snapResult.value = ''
  try {
    const out = await workspaceAdapter.windowSnapshot.restore()
    const detail = out.skipped.length
      ? ` · 跳过 ${out.skipped.length}：${out.skipped.map((s) => s.reason).join('/')}`
      : ''
    // 如实暴露匹配层（同运行期走 hwnd+pid；跨重启走 exePath 唯一候选）—— 不把"换了匹配依据"藏起来
    const layer =
      out.layer === 'same-run' ? '同运行期' : out.layer === 'cross-restart' ? '跨重启' : '未执行'
    snapResult.value = `快照：已恢复 ${out.restored.length} 个窗口（${layer}）${detail}`
    await refreshSnapStatus()
  } catch (e) {
    snapResult.value = `快照：恢复失败（${String((e as Error)?.message ?? e)}）`
  } finally {
    snapBusy.value = false
    void refresh()
  }
}

const placementText: Record<string, string> = {
  placed: '✓ 已摆位（等 facts 确认）',
  unbound: '未绑定当前工作模式 —— 拒绝摆位',
  offline: 'core 未连接 —— 摆位未执行',
  failed: '摆位失败',
}

/** C3 缩放方向（8 向）。左/上侧缩放在 previewGeometry 中同步移动 left/top。 */
const dirs = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as const

function openAi(): void {
  // AI 侧栏入口（原型：appbar 的 AI 标签 = dock 开关）。走既有 store 动作。
  if (ai.collapsed) ai.toggleCollapsed()
}

onMounted(() => {
  void refresh()
  void refreshSnapStatus()
  timer = window.setInterval(() => {
    clock.value = clockText()
    void refresh()
  }, 2000)
})
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
  detachInteraction()
})
</script>

<template>
  <div class="run-page">
    <!-- ===== run-head（原型 run-head：返回 / 名称 / 徽章 / 布局 seg / 时钟） ===== -->
    <header class="run-head">
      <button class="pw-btn pw-btn--ghost" data-pw="run-back" @click="router.back()">← 返回</button>
      <span v-if="modeMeta?.icon" class="run-emoji">{{ modeMeta.icon }}</span>
      <h1 class="pw-t-page run-title">{{ modeName || '工作模式' }}</h1>
      <span class="pw-chip pw-chip--brand" :class="{ 'is-live': !!modeName }" data-pw="run-live">
        {{ modeName ? '● 工作中' : '○ 未在模式中' }}
      </span>
      <span class="pw-grow"></span>
      <!-- 布局 / 排列 seg：C1 窗口控制未放开，可见但禁用（不提供假交互） -->
      <div class="run-seg" role="group" aria-label="布局模式" data-pw="run-layout-seg">
        <button class="run-seg__item is-active" disabled>自由</button>
        <button class="run-seg__item" disabled>自动整理</button>
        <button class="run-seg__item" disabled>聚焦</button>
      </div>
      <div class="run-seg" role="group" aria-label="排列模式" data-pw="run-arrange-seg">
        <button class="run-seg__item is-active" disabled>自动</button>
        <button class="run-seg__item" disabled>手动</button>
      </div>
      <button
        class="pw-btn pw-btn--sm"
        data-pw="run-layout-apply"
        :disabled="layoutBusy"
        title="应用当前模式绑定的布局（未运行的软件跳过，不自动启动）"
        @click="onLayoutApply()"
      >恢复默认</button>
      <button
        class="pw-btn pw-btn--sm pw-btn--primary"
        data-pw="run-layout-save"
        :disabled="layoutBusy"
        title="把当前受管窗口排布保存为布局（run-<模式名>-<时间戳>）"
        @click="onLayoutSave()"
      >保存布局</button>
      <span class="run-clock pw-mono">{{ clock }}</span>
    </header>

    <!-- ===== 状态栏（原型 #runStatus：任务 / 应用三态 / 布局 / 模式） ===== -->
    <div class="run-status" data-pw="run-status">
      <span class="pw-t-cap">当前任务</span>
      <span class="pw-chip">{{ modeDesc || '未设置' }}</span>
      <span class="run-status__sep"></span>
      <span class="pw-t-cap">应用</span>
      <template v-if="modeApps.length">
        <span
          v-for="a in modeApps"
          :key="a.appId ?? a.name"
          class="pw-chip"
          data-pw="run-app-chip"
          :title="runStateText[a.runState] ?? a.runState"
        >
          <span class="pw-dot" :class="dotOf(a.runState)"></span>
          {{ a.name }}<span v-if="a.windowCount > 0" class="run-chip__count">×{{ a.windowCount }}</span>
        </span>
      </template>
      <span v-else class="pw-chip pw-chip--outline">还没有应用在运行</span>
      <span class="run-status__sep"></span>
      <span class="pw-t-cap">布局</span>
      <span class="pw-chip" data-pw="run-layout-name-chip">{{ layoutName || '未绑定' }}</span>
      <span class="run-status__sep"></span>
      <span class="pw-t-cap">模式</span>
      <span class="pw-chip pw-chip--outline" data-pw="run-mode-chip">{{ modeName || '—' }}</span>
      <span class="pw-grow"></span>
      <!-- C5 布局结果（保存/应用共用一个 chip；detail 走 title，不压扁失败原因） -->
      <span
        v-if="layoutChip"
        class="pw-chip"
        data-pw="run-layout-chip"
        :title="layoutDetail"
      >{{ layoutChip }}</span>
      <!-- C3 摆位结果（§9 失败语义：placed/unbound/offline/failed，绝不假装成功） -->
      <!-- C4 快照（最小暴露：复用既有 pw-btn / pw-chip，零新视觉语言） -->
      <span class="pw-chip" data-pw="run-snap-chip">{{ snapshotText }}</span>
      <button
        class="pw-btn pw-btn--sm"
        data-pw="run-snap-save"
        :disabled="snapBusy"
        @click="onSnapshotSave()"
      >保存当前状态</button>
      <button
        class="pw-btn pw-btn--sm"
        data-pw="run-snap-restore"
        :disabled="snapBusy"
        @click="onSnapshotRestore()"
      >恢复上次状态</button>
      <span
        v-if="placement"
        class="pw-chip"
        data-pw="run-placement"
        :title="placement.message ?? ''"
      >
        <span class="pw-dot" :class="dotOf(placement.status === 'placed' ? 'running' : 'failed')"></span>
        {{ placementText[placement.status] ?? placement.status }}
      </span>
      <span v-if="loadError" class="run-status__warn" data-pw="run-degraded">{{ loadError }}</span>
    </div>

    <!-- ===== 主工作区域（窗口舞台画布；C3：归属当前模式的窗口可拖拽/缩放 → windows_place） ===== -->
    <div class="run-stage" data-pw="run-stage">
      <p class="run-stage__hint">
        舞台画布 · {{ connectivity === 'offline' ? '未连接' : `真实窗口投影 ${windowCount} 个` }}（摆位模式：拖拽/缩放即摆位，仅限当前模式窗口）
      </p>
      <div
        v-for="p in projections"
        :key="p.hwnd"
        class="run-win"
        :class="{ 'is-managed': p.mode }"
        :style="{ left: `${(p.x * 100).toFixed(2)}%`, top: `${(p.y * 100).toFixed(2)}%`, width: `${(p.w * 100).toFixed(2)}%`, height: `${(p.h * 100).toFixed(2)}%` }"
        :title="p.mode ? `${p.title} · 当前模式（可拖拽/缩放）` : `${p.title} · 非当前模式窗口（只读）`"
      >
        <span
          class="run-win__bar"
          :class="{ 'is-grab': p.mode }"
          @pointerdown="p.mode && startDrag($event, p.hwnd)"
        >{{ winBarText(p) }}</span>
        <!-- C3 缩放手势：8 向热区（只对归属窗口渲染）；左/上侧缩放会同步移动 left/top -->
        <template v-if="p.mode">
          <span v-for="d in dirs" :key="d" class="run-win__rz" :class="`run-win__rz--${d}`"
                @pointerdown="startResize($event, p.hwnd, d)"></span>
        </template>
      </div>
      <div v-if="!projections.length" class="run-stage__empty">
        <span class="pw-t-card">{{
          connectivity === 'offline'
            ? '未连接 core —— 无法读取真实窗口（不显示任何占位窗口）'
            : '画布空 —— 进入一个工作模式后，这里会显示它的真实窗口投影'
        }}</span>
      </div>
    </div>

    <!-- ===== 底部：appbar（软件标签 + AI 入口） + minimap ===== -->
    <footer class="run-foot">
      <div class="run-appbar" data-pw="run-appbar">
        <template v-if="modeApps.length">
          <button
            v-for="a in modeApps"
            :key="a.appId ?? a.name"
            class="run-tab"
            disabled
            :title="`${runStateText[a.runState] ?? a.runState}（窗口激活属 C3）`"
          >
            <span class="pw-dot" :class="dotOf(a.runState)"></span>
            {{ a.name }}
          </button>
        </template>
        <span v-else class="run-tab run-tab--ghost">软件标签页</span>
        <span class="pw-grow"></span>
        <button class="run-tab run-tab--ai" data-pw="run-ai-tab" @click="openAi()">AI</button>
      </div>
      <div class="run-minimap" data-pw="run-minimap" aria-label="窗口排布缩略图">
        <div
          v-for="p in projections"
          :key="p.hwnd"
          class="run-minimap__win"
          :style="{ left: `${(p.x * 100).toFixed(2)}%`, top: `${(p.y * 100).toFixed(2)}%`, width: `${(p.w * 100).toFixed(2)}%`, height: `${(p.h * 100).toFixed(2)}%` }"
        ></div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* 视觉纪律：只用 token（语义层优先），零裸色值 / 零新字体 / 零动画新曲线。 */
.run-page {
  display: flex;
  flex-direction: column;
  gap: var(--f-space-4);
  height: 100%;
  padding: var(--f-space-5) var(--f-space-8) var(--f-space-6);
  background: var(--bg-canvas);
  color: var(--text-1);
}

.run-head {
  display: flex;
  align-items: center;
  gap: var(--f-space-3);
}
.run-emoji {
  font-size: var(--fs-num-lg, 22px);
}
.run-title {
  margin: 0;
}
.run-clock {
  color: var(--text-3);
}

.run-seg {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  overflow: hidden;
}
.run-seg__item {
  padding: 4px var(--f-space-3);
  font-size: var(--fs-caption, 12px);
  background: var(--surface-2);
  color: var(--text-2);
  border: 0;
  border-right: 1px solid var(--border);
  cursor: not-allowed;
}
.run-seg__item:last-child {
  border-right: 0;
}
.run-seg__item.is-active {
  background: var(--brand-50);
  color: var(--brand-600);
  font-weight: 600;
}

.run-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--f-space-2);
  padding: var(--f-space-2) var(--f-space-4);
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}
.run-status__sep {
  width: 1px;
  height: var(--f-space-4);
  background: var(--border-subtle);
}
.run-status__warn {
  color: var(--warning);
  font-size: var(--fs-caption, 12px);
}
/* C2：软件 chip 的窗口计数后缀（只用既有 token，零新色）。 */
.run-chip__count {
  margin-left: 2px;
  color: var(--text-3);
  font-size: var(--fs-caption, 12px);
}

.run-stage {
  position: relative;
  flex: 1;
  min-height: var(--f-space-12);
  background: var(--bg-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  overflow: hidden;
}
.run-stage__hint {
  position: absolute;
  top: var(--f-space-2);
  left: var(--f-space-3);
  margin: 0;
  color: var(--text-4);
  font-size: var(--fs-label, 11px);
  letter-spacing: 0.06em;
}
.run-stage__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-4);
}
/* 真实窗口投影：几何来自 windows facts，样式是原型的卡窗语言（r-lg 卡 + 细 bar）。 */
.run-win {
  position: absolute;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  opacity: 0.92;
  overflow: hidden;
}
/* C3：非当前模式窗口保持只读（整卡不接指针）；归属窗口仅 bar/handle 接收事件。 */
.run-win:not(.is-managed) {
  pointer-events: none;
}
.run-win__bar.is-grab {
  cursor: grab;
}
.run-win__bar.is-grab:active {
  cursor: grabbing;
}
/* C3 缩放热区（8 向）：内侧热区（.run-win overflow:hidden 裁外侧），hover 提示线，全部既有 token，零动画。 */
.run-win__rz {
  position: absolute;
  background: transparent;
  z-index: 2;
}
.run-win__rz:hover {
  background: var(--brand-200, var(--brand-500));
  opacity: 0.5;
}
.run-win__rz--n,
.run-win__rz--s {
  left: 6px;
  right: 6px;
  height: 5px;
  cursor: ns-resize;
}
.run-win__rz--n {
  top: 0;
}
.run-win__rz--s {
  bottom: 0;
}
.run-win__rz--e,
.run-win__rz--w {
  top: 6px;
  bottom: 6px;
  width: 5px;
  cursor: ew-resize;
}
.run-win__rz--e {
  right: 0;
}
.run-win__rz--w {
  left: 0;
}
.run-win__rz--nw,
.run-win__rz--ne,
.run-win__rz--sw,
.run-win__rz--se {
  width: 10px;
  height: 10px;
}
.run-win__rz--nw {
  top: 0;
  left: 0;
  cursor: nwse-resize;
}
.run-win__rz--ne {
  top: 0;
  right: 0;
  cursor: nesw-resize;
}
.run-win__rz--sw {
  bottom: 0;
  left: 0;
  cursor: nesw-resize;
}
.run-win__rz--se {
  bottom: 0;
  right: 0;
  cursor: nwse-resize;
}
.run-win__bar {
  display: block;
  padding: 2px var(--f-space-2);
  font-size: var(--fs-label, 11px);
  color: var(--text-3);
  background: var(--surface-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.run-foot {
  display: flex;
  align-items: center;
  gap: var(--f-space-4);
}
.run-appbar {
  display: flex;
  align-items: center;
  gap: var(--f-space-2);
  flex: 1;
  min-width: 0;
  padding: var(--f-space-2);
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}
.run-tab {
  padding: 4px var(--f-space-3);
  font-size: var(--fs-caption, 12px);
  color: var(--text-2);
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-controls);
  cursor: not-allowed;
}
.run-tab--ghost {
  color: var(--text-4);
  border-style: dashed;
}
.run-tab--ai {
  cursor: pointer;
  background: var(--brand-50);
  color: var(--brand-600);
  border-color: transparent;
  font-weight: 600;
}
.run-minimap {
  position: relative;
  width: 192px;
  height: 108px;
  flex: none;
  background: var(--bg-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-controls);
  overflow: hidden;
}
.run-minimap__win {
  position: absolute;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 2px;
}
</style>
