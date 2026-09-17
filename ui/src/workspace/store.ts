/**
 * Workspace Runtime —— 内存状态存储（TECH-02）
 *
 * ## 这一层是什么
 * UI-05-B 的「工作空间状态系统」此前把状态写在页面内部的 mock 对象里（UI 直读 mock）。
 * 本模块把状态**收进一个内存 store**，由 `runtime.ts` 暴露读取/变更 API，UI 只经 API 取数。
 *
 * ```
 * 改造前：  UI ──直接读──> mock 对象 ──> render
 * 改造后：  UI ──> workspaceRuntime API ──> memory store（本文件）──> UI 订阅后 render
 * ```
 *
 * ## 硬边界（TECH-02 §七，不可越）
 * - **零数据库**：全部状态活在内存里（`Map` + 普通对象），刷新即重置。
 * - **零 core**：不 import `@/api/*`，不发 invoke、不发 HTTP。
 * - **零真实软件控制**：`status` 只是数据，不代表任何真实进程。
 * - **零窗口系统接管**：不碰 Win32；窗口几何是 **DOM 几何**（见 `layout.ts`）。
 * - **零动画 / 零 Motion**：不 import `@/motion/*`（`prepareWorkspace` 也不得触发动效）。
 *
 * ## 为什么 store 不 import Vue
 * 运行时是**框架无关**的：将来 TECH-03 的真实 Agent / 软件控制层要复用同一份状态，
 * 不能要求对方装 Vue。所以本层用显式 `subscribe()` 订阅，UI 侧自己接进响应式系统。
 *
 * ## 唯一的写入者 + 结构级防篡改
 * 本文件不导出内部 `state` 对象；所有对外返回的结构都是**深克隆 + 冻结**
 * （`deepFreeze`）。因此 UI 拿到手也改不动真身 —— 这是「UI 不直接访问 mock」的
 * **结构级保证**，不是口头约定。
 */

// ---------------------------------------------------------------- 数据模型

/** 应用在工作空间内的状态。`waiting` = 已登记但窗口未就绪。 */
export type AppStatus = 'running' | 'waiting' | 'closed'

/** 布局来源：`auto` = 由 UI 自动排布；`manual` = 来自某个快照。 */
export type LayoutType = 'auto' | 'manual'

/** 窗口事件种类（TECH-02 §五；当前只更新 Runtime，不连接真实软件）。 */
export type WindowEventKind = 'open' | 'close' | 'focus'

/** 工作空间内的一个应用。 */
export interface WorkspaceApp {
  appId: string
  name: string
  status: AppStatus
  /** 窗口标识。`running` / `waiting` 有，`closed` 无。 */
  windowId?: string
  /** 布局节点标识。仅 `running` 有（`waiting` 尚未落到布局树）。 */
  layoutNode?: string
}

/** 工作空间布局描述（**不含几何**；几何在 `LayoutSnapshot` 里）。 */
export interface WorkspaceLayout {
  type: LayoutType
  snapshotId?: string
}

/** 一个工作空间的完整运行时状态（TECH-02 §一 的 `WorkspaceRuntime`）。 */
export interface WorkspaceRuntime {
  workspaceId: string
  name: string
  goal: string
  mode: string
  apps: WorkspaceApp[]
  layout: WorkspaceLayout
}

/**
 * 布局快照里的**单条 DOM 几何**（TECH-02 §三 指定的六个字段，一个不多）。
 *
 * ⚠️ 与 `workspace.snapshot.last`（PW-INTEGRATION-003 §2，**系统级窗口**快照、core 落库）
 * 是**两个不同的东西**：本快照只记**应用内部 DOM 的几何**，永不接触真实系统窗口、永不落库。
 */
export interface LayoutSnapshotEntry {
  appId: string
  x: number
  y: number
  width: number
  height: number
  zIndex: number
}

/** 一次布局快照。 */
export interface LayoutSnapshot {
  snapshotId: string
  workspaceId: string
  createdAt: number
  entries: LayoutSnapshotEntry[]
}

/**
 * 工作空间模板（TECH-02 §四）：模板**自己拥有** apps 与 layoutSnapshot。
 * 字段严格按 §四 的 `{id,name,goal,apps[],layoutSnapshot}`，不额外挂字段。
 */
export interface WorkspaceTemplate {
  id: string
  name: string
  goal: string
  apps: Array<{ appId: string; name: string }>
  layoutSnapshot: LayoutSnapshot | null
}

/** `windowEvent()` 的入参（TECH-02 §五）。 */
export interface WindowEventInput {
  windowId: string
  event: WindowEventKind
}

/** `prepareWorkspace()` 流水线的一步。 */
export interface PrepareStep {
  step: string
  ok: boolean
  detail: string
}

/** `prepareWorkspace()` 的结果。 */
export interface PrepareReport {
  ok: boolean
  workspaceId: string
  templateId: string | null
  mode: string
  steps: PrepareStep[]
  usedSnapshotId: string | null
  apps: WorkspaceApp[]
  layout: WorkspaceLayout
  ms: number
}

/** 订阅回调收到的变更信息。 */
export interface MutationInfo {
  revision: number
  reason: string
}

// ---------------------------------------------------------------- 种子数据

/**
 * 种子模板 —— **模块私有，绝不导出**。
 *
 * `verify_tech02_workspace.py` 的 T1 会静态断言：`__SEED_TEMPLATES` 这个名字
 * 只允许出现在本文件里；UI 侧拿不到它，只能经 `workspaceRuntime.listTemplates()` 取数。
 */
const __SEED_TEMPLATES: readonly WorkspaceTemplate[] = [
  {
    id: 'tpl-seed-dev',
    name: 'AI 开发',
    goal: '把当天的开发任务推进到可提交状态',
    apps: [
      { appId: 'vscode', name: 'VS Code' },
      { appId: 'terminal', name: 'Terminal' },
      { appId: 'apidocs', name: '接口文档' },
    ],
    layoutSnapshot: null,
  },
  {
    id: 'tpl-seed-write',
    name: '写作',
    goal: '完成一篇长文的初稿',
    apps: [
      { appId: 'editor', name: '写作器' },
      { appId: 'notes', name: '素材库' },
    ],
    layoutSnapshot: null,
  },
  {
    id: 'tpl-seed-study',
    name: '学习',
    goal: '完成今日学习节点的练习',
    apps: [
      { appId: 'reader', name: '阅读器' },
      { appId: 'notepad', name: '笔记' },
      { appId: 'timer', name: '番茄钟' },
    ],
    layoutSnapshot: null,
  },
]

// ---------------------------------------------------------------- 内部状态

interface StoreState {
  revision: number
  current: WorkspaceRuntime | null
  templates: WorkspaceTemplate[]
  snapshots: Map<string, LayoutSnapshot>
  lastWindowEvent: { windowId: string; event: WindowEventKind; at: number } | null
  focusedWindowId: string | null
}

const state: StoreState = {
  revision: 0,
  current: null,
  templates: __SEED_TEMPLATES.map(clone),
  snapshots: new Map<string, LayoutSnapshot>(),
  lastWindowEvent: null,
  focusedWindowId: null,
}

let seq = 0
function nextId(prefix: string): string {
  seq += 1
  return `${prefix}-${seq}`
}

// ---------------------------------------------------------------- 工具

function clone<T>(value: T): T {
  // 数据全是 JSON 友好的普通结构 —— 用 JSON 往返即可，不依赖 structuredClone 的可用性。
  return JSON.parse(JSON.stringify(value)) as T
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    for (const key of Object.keys(value as Record<string, unknown>)) {
      deepFreeze((value as Record<string, unknown>)[key])
    }
    Object.freeze(value)
  }
  return value
}

/** 窗口标识约定：`win-<appId>`。`windowEvent()` 靠它反查应用。 */
export function windowIdOf(appId: string): string {
  return `win-${appId}`
}

/** 布局节点标识约定：`node-<appId>`（仅 `running` 时分配）。 */
function layoutNodeOf(appId: string): string {
  return `node-${appId}`
}

// ---------------------------------------------------------------- 订阅

type Listener = (info: MutationInfo) => void
const listeners = new Set<Listener>()

/** 订阅状态变更。返回值是取消订阅函数。 */
export function subscribe(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

function notify(reason: string): void {
  state.revision += 1
  const info: MutationInfo = { revision: state.revision, reason }
  for (const fn of Array.from(listeners)) {
    try {
      fn(info)
    } catch {
      /* 单个订阅者抛错不得影响其余订阅者 */
    }
  }
}

/** 当前修订号（每次状态变更 +1）—— UI / 验收可据此判断"数据真的动了"。 */
export function getRevision(): number {
  return state.revision
}

// ---------------------------------------------------------------- 只读查询

/** 当前工作空间（**深克隆 + 冻结**，调用方改不动真身）。 */
export function getSnapshot(): WorkspaceRuntime | null {
  return state.current ? deepFreeze(clone(state.current)) : null
}

/** 当前工作空间的应用列表（**深克隆 + 冻结**）。 */
export function getAppsSnapshot(): WorkspaceApp[] {
  return deepFreeze(clone(state.current?.apps ?? []))
}

/** 当前工作空间的布局描述（**深克隆 + 冻结**）。 */
export function getLayoutMeta(): WorkspaceLayout | null {
  return state.current ? deepFreeze(clone(state.current.layout)) : null
}

/** 全部模板（**深克隆 + 冻结**）。 */
export function listTemplates(): WorkspaceTemplate[] {
  return deepFreeze(clone(state.templates))
}

/** 按 id 或名称取模板。 */
export function findTemplate(idOrName: string): WorkspaceTemplate | null {
  const t = state.templates.find((x) => x.id === idOrName || x.name === idOrName)
  return t ? deepFreeze(clone(t)) : null
}

/** 最近一次 `windowEvent`（供 UI / 验收观察）。 */
export function lastWindowEvent(): { windowId: string; event: WindowEventKind; at: number } | null {
  return state.lastWindowEvent ? deepFreeze(clone(state.lastWindowEvent)) : null
}

/** 当前持有焦点的窗口标识。 */
export function focusedWindowId(): string | null {
  return state.focusedWindowId
}

/** 按 id 取布局快照。 */
export function findSnapshot(snapshotId: string): LayoutSnapshot | null {
  const s = state.snapshots.get(snapshotId)
  return s ? deepFreeze(clone(s)) : null
}

/** 列出某工作空间的全部布局快照。 */
export function listSnapshots(workspaceId?: string): LayoutSnapshot[] {
  const all = Array.from(state.snapshots.values()).filter(
    (s) => !workspaceId || s.workspaceId === workspaceId,
  )
  return deepFreeze(clone(all))
}

/** 生成一个模板 id。 */
export function newTemplateId(): string {
  return nextId('tpl')
}

/** 生成一个布局快照 id。 */
export function newSnapshotId(): string {
  return nextId('lsnap')
}

// ---------------------------------------------------------------- 受控变更

/**
 * 应用状态机（**唯一实现**，`runtime.ts` 的 prepare 流水线也复用它，避免两处规则漂移）：
 * `running` 分配 windowId + layoutNode；`waiting` 只分配 windowId；`closed` 两个都不留。
 */
export function applyStatusToDraft(app: WorkspaceApp, status: AppStatus): void {
  app.status = status
  if (status === 'closed') {
    delete app.windowId
    delete app.layoutNode
    return
  }
  app.windowId = windowIdOf(app.appId)
  if (status === 'running') {
    app.layoutNode = layoutNodeOf(app.appId)
  } else {
    delete app.layoutNode
  }
}

/**
 * 更新某个应用的状态（TECH-02 §二）。
 * 返回**变更后的应用副本**（冻结）；无工作空间或 appId 未知时返回 `null`。
 */
export function updateAppStatus(appId: string, status: AppStatus): WorkspaceApp | null {
  const ws = state.current
  if (!ws) return null
  const app = ws.apps.find((a) => a.appId === appId)
  if (!app) return null
  applyStatusToDraft(app, status)
  // 窗口不再处于 running 时释放焦点环，避免 UI 显示一个"不存在的焦点"
  if (status !== 'running' && state.focusedWindowId === windowIdOf(appId)) {
    state.focusedWindowId = null
  }
  notify(`status:${appId}:${status}`)
  return deepFreeze(clone(app))
}

/**
 * 接收窗口事件（TECH-02 §五）。**只更新 Runtime，不连接真实软件。**
 *
 * 映射：`open` → `running`；`close` → `closed`；`focus` → 状态不变，只改焦点（并把 zIndex 顶到最上）。
 * `windowId` 匹配不到任何应用时返回 `null`（事件被记录，但不改状态）。
 */
export function applyWindowEvent(input: WindowEventInput): WorkspaceApp | null {
  const ws = state.current
  state.lastWindowEvent = { windowId: input.windowId, event: input.event, at: Date.now() }
  if (!ws) {
    notify('window-event-no-workspace')
    return null
  }
  const app = ws.apps.find((a) => a.windowId === input.windowId)
  if (!app) {
    notify('window-event-unmatched')
    return null
  }
  if (input.event === 'open') {
    applyStatusToDraft(app, 'running')
    notify(`window-open:${app.appId}`)
  } else if (input.event === 'close') {
    applyStatusToDraft(app, 'closed')
    if (state.focusedWindowId === input.windowId) state.focusedWindowId = null
    notify(`window-close:${app.appId}`)
  } else {
    state.focusedWindowId = input.windowId
    bumpZIndex(ws.workspaceId, app.appId)
    notify(`window-focus:${app.appId}`)
  }
  return deepFreeze(clone(app))
}

/** `focus` 时把该应用在快照里的 zIndex 顶到最上层（焦点落在视觉上层，语义一致）。 */
function bumpZIndex(workspaceId: string, appId: string): void {
  const id = state.current?.layout.snapshotId
  if (!id) return
  const snap = state.snapshots.get(id)
  if (!snap || snap.workspaceId !== workspaceId) return
  const max = snap.entries.reduce((m, e) => Math.max(m, e.zIndex), 0)
  const entry = snap.entries.find((e) => e.appId === appId)
  if (entry) entry.zIndex = max + 1
}

/** 新增模板。 */
export function addTemplate(tpl: WorkspaceTemplate): WorkspaceTemplate {
  state.templates.push(clone(tpl))
  notify(`template-add:${tpl.id}`)
  return deepFreeze(clone(tpl))
}

/** 存入布局快照，并把 current 的 layout 标为 `manual`。 */
export function putSnapshot(snap: LayoutSnapshot): LayoutSnapshot {
  state.snapshots.set(snap.snapshotId, clone(snap))
  const ws = state.current
  if (ws && ws.workspaceId === snap.workspaceId) {
    ws.layout = { type: 'manual', snapshotId: snap.snapshotId }
  }
  notify(`snapshot-put:${snap.snapshotId}`)
  return deepFreeze(clone(snap))
}

/** 把 current 的 layout 指向某个已存在的快照。 */
export function bindSnapshot(snapshotId: string): LayoutSnapshot | null {
  const snap = state.snapshots.get(snapshotId)
  if (!snap) return null
  const ws = state.current
  if (!ws) return null
  ws.layout = { type: 'manual', snapshotId }
  notify(`snapshot-bind:${snapshotId}`)
  return deepFreeze(clone(snap))
}

/** 清除某工作空间的全部快照，并把 layout 回落成 `auto`。返回清除条数。 */
export function clearSnapshotsFor(workspaceId: string): number {
  let removed = 0
  for (const [id, snap] of Array.from(state.snapshots.entries())) {
    if (snap.workspaceId === workspaceId) {
      state.snapshots.delete(id)
      removed += 1
    }
  }
  const ws = state.current
  if (ws && ws.workspaceId === workspaceId) ws.layout = { type: 'auto' }
  notify(`snapshot-clear:${workspaceId}`)
  return removed
}

/** 用模板生成一个工作空间对象（纯数据，不改 store）。初始 apps 全部 `waiting`。 */
export function buildWorkspace(tpl: WorkspaceTemplate, mode = 'default'): WorkspaceRuntime {
  return {
    workspaceId: nextId('ws'),
    name: tpl.name,
    goal: tpl.goal,
    mode,
    apps: tpl.apps.map((a) => ({ appId: a.appId, name: a.name, status: 'waiting' as AppStatus })),
    layout: { type: 'auto' },
  }
}

/**
 * 内部：把 `runtime.ts` 的 prepare 流水线组装好的工作空间**一次性**装上并通知一次。
 *
 * 为什么不让流水线逐步调 `updateAppStatus`：那会产生 N 次通知 → UI 侧 N 次 diff
 * —— 正是 S2 要避免的"更新状态引发整页刷新"的反面（一次通知 = 一次局部 diff）。
 */
export function commitWorkspace(ws: WorkspaceRuntime, reason: string): void {
  state.current = clone(ws)
  state.focusedWindowId = null
  notify(reason)
}

/** 内部：读取可供流水线修改的当前工作空间副本（返回副本，改它不影响 store）。 */
export function draftCurrent(): WorkspaceRuntime | null {
  return state.current ? clone(state.current) : null
}
