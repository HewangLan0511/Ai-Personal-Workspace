/**
 * Workspace Runtime —— 对外门面（TECH-02 §一/§二/§四/§五/§六）
 *
 * ## 为什么需要它
 * UI 只应该通过**这一个入口**读/改工作空间状态，这样：
 * - 数据来源可以整体替换（现在的 memory store → TECH-03 的真实 Agent / 软件控制层）而不动 UI；
 * - `prepareWorkspace()` 是**异步**的，接真实后端时接口形状不用改（"保持异步结构"的用意）。
 *
 * ```
 *   UI ──> workspaceRuntime.* ──┬─> store.ts   （内存状态：工作空间 / 应用 / 模板 / 快照）
 *                               └─> layout.ts  （DOM 几何：保存 / 恢复 / 清除）
 * ```
 *
 * ## 本层**不做**什么（TECH-02 §七 + §十）
 * 不启动真实软件、不控制系统窗口、不连插件、不做 AI 规划 —— 这些属 TECH-03。
 * 不 import `@/api/*`（零 core）、不 import `@/motion/*`（零动画 / 不改 Motion Runtime）、
 * 不引数据库（零持久化）。
 *
 * ## 未来接口已经留好
 * - `windowEvent()` —— TECH-03 的真实窗口事件从这里灌进来即可；
 * - `prepareWorkspace()` 返回 `Promise` —— 换成真实软件启动后签名不变；
 * - `subscribe()` —— 推送式更新，天然适配"后端推状态"。
 */

import {
  addTemplate,
  applyStatusToDraft,
  applyWindowEvent,
  buildWorkspace,
  commitWorkspace,
  draftCurrent,
  findSnapshot,
  findTemplate,
  focusedWindowId,
  getAppsSnapshot,
  getLayoutMeta,
  getRevision,
  getSnapshot,
  lastWindowEvent,
  listTemplates,
  newTemplateId,
  putSnapshot,
  subscribe,
  updateAppStatus,
  type AppStatus,
  type LayoutSnapshot,
  type PrepareReport,
  type PrepareStep,
  type WindowEventInput,
  type WorkspaceApp,
  type WorkspaceLayout,
  type WorkspaceRuntime,
  type WorkspaceTemplate,
} from './store'
import {
  applyLayoutToDom,
  clearLayoutSnapshot,
  getLayoutSnapshot,
  listLayoutSnapshots,
  loadLayoutSnapshot,
  saveLayoutSnapshot,
} from './layout'
import {
  capture as captureSnapshot,
  restore as restoreSnapshot,
  validate as validateSnapshot,
  type CaptureOptions,
  type CaptureOutcome,
  type RestoreOptions,
  type RestorePlan,
  type SnapshotValidation,
  type WindowProbe,
  type WorkspaceSnapshotV1,
} from './snapshot'

// 类型再导出：UI 只 import 本文件即可拿到全部类型
export type {
  AppStatus,
  LayoutSnapshot,
  LayoutSnapshotEntry,
  LayoutType,
  MutationInfo,
  PrepareReport,
  PrepareStep,
  WindowEventInput,
  WindowEventKind,
  WorkspaceApp,
  WorkspaceLayout,
  WorkspaceRuntime,
  WorkspaceTemplate,
} from './store'
export type {
  CaptureOptions,
  CaptureOutcome,
  RestoreOptions,
  RestorePlan,
  RestoreStep,
  RestoreStepKind,
  SnapshotIssue,
  SnapshotValidation,
  WindowProbe,
  WorkspaceSnapshotV1,
} from './snapshot'

/** `createTemplate()` 入参。 */
export interface CreateTemplateInput {
  name: string
  goal?: string
  /** 省略则取当前工作空间的应用；两者都没有时报错。 */
  apps?: Array<{ appId: string; name: string }>
  /** 省略（且当前有画布）则现场采一份 DOM 几何快照；传 `null` 表示明确不要快照。 */
  layoutSnapshot?: LayoutSnapshot | null
}

/** `prepareWorkspace()` 选项。 */
export interface PrepareOptions {
  /**
   * 每步之间的让出时延（ms）。默认 0（真异步但不等）。
   * 验收脚本会调大（如 8ms）来**证明异步结构真实存在**而不是同步假装。
   */
  stepDelayMs?: number
  /** 工作空间模式标识。模板契约里没有 mode（§四 的字段表），故默认 `default`。 */
  mode?: string
  /** 逐步进度回调（UI 可据此显示准备清单，不必新增动画）。 */
  onProgress?: (step: PrepareStep) => void
}

/**
 * prepare 流水线的**固定步骤序列 —— 顺序即契约**。
 * 验收脚本会拿它和 `report.steps` 逐项比对；插队/少步都会变红。
 */
export const PREPARE_STEPS = [
  'read-workspace',
  'read-layout-snapshot',
  'sync-app-status',
  'commit',
] as const

function now(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function wait(ms: number): Promise<void> {
  if (ms <= 0) return Promise.resolve()
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

/**
 * 准备一个工作空间（TECH-02 §六）。
 *
 * ```
 * 点击模板 → prepareWorkspace(id)
 *              ① read-workspace        读取工作空间（模板 → 工作空间对象）
 *              ② read-layout-snapshot  读取布局快照（模板自带 / 已注册）
 *              ③ sync-app-status       同步 app 状态（快照覆盖到的 = running，其余 = waiting）
 *              ④ commit                一次性提交并通知（单次通知 → UI 侧一次局部 diff）
 *            → 进入 run（由 UI 决定何时渲染）
 * ```
 *
 * 现在全是内存数据，但**流水线是真异步**（每步之间 await），所以将来把第①②步换成
 * "真实软件启动 / 真实窗口就位"时，调用方一行都不用改。
 *
 * 注意：快照的 **DOM 应用由 UI 负责**（只有 UI 知道窗口何时渲染出来）；
 * 本函数只保证"数据就位 + `layout` 指向该快照"。
 */
export async function prepareWorkspace(
  id: string,
  opts: PrepareOptions = {},
): Promise<PrepareReport> {
  const stepDelay = Math.max(0, opts.stepDelayMs ?? 0)
  const t0 = now()
  const steps: PrepareStep[] = []
  const push = (step: string, ok: boolean, detail: string): void => {
    const s: PrepareStep = { step, ok, detail }
    steps.push(s)
    opts.onProgress?.(s)
  }
  const mode = opts.mode ?? 'default'

  // ---- ① 读取工作空间 ----
  await wait(stepDelay)
  const tpl = findTemplate(id)
  const existing = getSnapshot()
  let workspace: WorkspaceRuntime
  let templateId: string | null = null

  if (tpl) {
    templateId = tpl.id
    workspace = buildWorkspace(tpl, mode)
    push('read-workspace', true, `来自模板「${tpl.name}」（${tpl.apps.length} 个应用）`)
  } else if (existing && existing.workspaceId === id) {
    workspace = draftCurrent() ?? {
      workspaceId: id,
      name: existing.name,
      goal: existing.goal,
      mode,
      apps: [],
      layout: { type: 'auto' },
    }
    push('read-workspace', true, `来自当前工作空间「${existing.name}」`)
  } else {
    push('read-workspace', false, `找不到工作空间 / 模板：${id}`)
    return {
      ok: false,
      workspaceId: id,
      templateId: null,
      mode,
      steps,
      usedSnapshotId: null,
      apps: [],
      layout: { type: 'auto' },
      ms: now() - t0,
    }
  }

  // ---- ② 读取布局快照 ----
  await wait(stepDelay)
  let snapshot: LayoutSnapshot | null = tpl?.layoutSnapshot ?? null
  if (snapshot && !findSnapshot(snapshot.snapshotId)) {
    // 模板自带快照但还没注册进 store（例如来自别处导入的模板）→ 补登记，
    // 否则第③步会静默把全部应用降成 waiting（模板与工作空间又变回浅绑定）。
    putSnapshot(snapshot)
  }
  const usedSnapshotId = snapshot ? snapshot.snapshotId : null
  push(
    'read-layout-snapshot',
    true,
    snapshot
      ? `命中快照 ${snapshot.snapshotId}（${snapshot.entries.length} 条几何）`
      : '无快照 → layout 走 auto',
  )
  workspace.layout = usedSnapshotId ? { type: 'manual', snapshotId: usedSnapshotId } : { type: 'auto' }

  // ---- ③ 同步 app 状态 ----
  await wait(stepDelay)
  const covered = new Set(snapshot?.entries.map((e) => e.appId) ?? [])
  for (const app of workspace.apps) {
    applyStatusToDraft(app, covered.has(app.appId) ? 'running' : 'waiting')
  }
  const runningCount = workspace.apps.filter((a) => a.status === 'running').length
  push(
    'sync-app-status',
    true,
    `running ${runningCount} / waiting ${workspace.apps.length - runningCount}`,
  )

  // ---- ④ 提交（单次通知）----
  await wait(stepDelay)
  commitWorkspace(workspace, `prepare:${templateId ?? workspace.workspaceId}`)
  push('commit', true, `workspaceId=${workspace.workspaceId} rev=${getRevision()}`)

  return {
    ok: true,
    workspaceId: workspace.workspaceId,
    templateId,
    mode,
    steps,
    usedSnapshotId,
    apps: getAppsSnapshot(),
    layout: getLayoutMeta() ?? { type: 'auto' },
    ms: now() - t0,
  }
}

// ---------------------------------------------------------------- 快照接入（TECH-04 §二）

/**
 * 恢复可用性读模型（TECH-04 §二 的"UI 可读取"三件事）。
 *
 * **它是一片只读视图**：不含任何可执行入口 —— 不移动系统窗口、不杀进程、
 * 不修改外部软件状态。`recovery.executable` 写死为 `false`，与本轮的禁止项一一对应。
 */
export interface WorkspaceRecoveryStatus {
  /** 生成这块视图的时间戳。 */
  at: number
  /** 一、当前工作空间状态 */
  workspace: {
    workspaceId: string | null
    name: string | null
    mode: string | null
    appCount: number
    runningCount: number
    waitingCount: number
  }
  /** 二、最近布局状态 */
  layout: {
    type: 'auto' | 'manual' | null
    snapshotId: string | null
    entryCount: number
    /** 已注册的布局快照份数。 */
    snapshotCount: number
    /** 已持久化的 v1 快照 id（需外部注入读取器；未注入时为 `null`）。 */
    persistedSnapshotId: string | null
    /** 已持久化快照是否通过 v1 契约校验。 */
    persistedValid: boolean
  }
  /** 三、恢复可用性 */
  recovery: {
    available: boolean
    /** **恒为 `false`** —— 本轮只做接口准备，不执行窗口/进程操作。 */
    executable: false
    /** 阻塞原因（如 `probe-not-wired` / `no-workspace` / `runid-mismatch`）。 */
    blockers: string[]
    reason: string
    /** 四条红线（不杀进程 / 不启动软件 / 不写库 / 不碰未登记窗口）—— 恒为 false。 */
    guardrails: RestorePlan['guardrails']
    /** 持久快照的 runId 与当前是否一致；未注入 runId 时为 `null`（未知）。 */
    runIdMatch: boolean | null
    /** 若能算出计划，计划里有几步。 */
    planStepCount: number
  }
}

/** 窗口探针（真实采集的注入点）。本轮不注入 ⇒ `capture()` 恒 `dryRun`。 */
let injectedProbe: WindowProbe | null = null
/** 已持久化 v1 快照的读取器。**由外部适配器提供本层不碰 core**（零 core 约束）。 */
let persistedReader: (() => unknown | null) | null = null
/** 当前 core 运行期标识；`null` = 未知（此时不判断 hwnd 是否失效）。 */
let currentRunId: string | null = null

/** 深冻结一个只读视图（与外层 `getAppsSnapshot()` 的纪律一致）。 */
function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value)
    for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v)
  }
  return value
}

/**
 * 组装"当前工作空间状态 + 最近布局状态 + 恢复可用性"（TECH-04 §二）。
 *
 * 全部来自**只读**能力：内存 store 的当前值 + DOM 布局快照的元信息 +
 * （若注入）持久化 v1 快照的校验/计划。**不产生任何副作用**。
 */
export function getRecoveryStatus(): WorkspaceRecoveryStatus {
  const cur = getSnapshot()
  const apps = getAppsSnapshot()
  const meta = getLayoutMeta()
  const snaps = listLayoutSnapshots()
  const lastLayout = snaps.length ? snaps[snaps.length - 1] : null

  const persisted = persistedReader ? persistedReader() : null
  const hasPersisted = persisted !== null && persisted !== undefined
  const validation: SnapshotValidation | null = hasPersisted ? validateSnapshot(persisted) : null
  const persistedSnap = hasPersisted ? (persisted as WorkspaceSnapshotV1) : null

  const runIdKnown = currentRunId !== null
  const plan: RestorePlan | null =
    validation && validation.ok
      ? restoreSnapshot(persisted, runIdKnown ? { currentRunId: currentRunId! } : {})
      : null
  const runIdMatch = runIdKnown && plan ? plan.runIdMatch : null

  const wired = !!(injectedProbe && injectedProbe.wired)
  const blockers: string[] = []
  if (!wired) blockers.push('probe-not-wired')
  if (!cur) blockers.push('no-workspace')
  if (hasPersisted && validation && !validation.ok) blockers.push('persisted-snapshot-invalid')
  if (runIdMatch === false) blockers.push('runid-mismatch')

  const available =
    wired && cur !== null && validation !== null && validation.ok && runIdMatch !== false

  const reason = available
    ? '接口就绪且存在可用的 v1 快照（执行侧仍未放开 —— 本轮只准备接口）'
    : blockers.length
      ? `不可恢复：${blockers.join(' / ')}`
      : '不可恢复：缺少已持久化的 v1 快照'

  return deepFreeze({
    at: now(),
    workspace: {
      workspaceId: cur ? cur.workspaceId : null,
      name: cur ? cur.name : null,
      mode: cur ? cur.mode : null,
      appCount: apps.length,
      runningCount: apps.filter((a) => a.status === 'running').length,
      waitingCount: apps.filter((a) => a.status === 'waiting').length,
    },
    layout: {
      type: meta ? meta.type : null,
      snapshotId: meta && meta.snapshotId ? meta.snapshotId : null,
      entryCount: lastLayout ? lastLayout.entries.length : 0,
      snapshotCount: snaps.length,
      persistedSnapshotId: persistedSnap ? persistedSnap.snapshotId : null,
      persistedValid: validation ? validation.ok : false,
    },
    recovery: {
      available,
      executable: false,
      blockers,
      reason,
      guardrails: {
        killsProcesses: false,
        launchesApps: false,
        writesDatabase: false,
        touchesUnmanagedWindows: false,
      },
      runIdMatch,
      planStepCount: plan ? plan.steps.length : 0,
    },
  }) as WorkspaceRecoveryStatus
}

/**
 * 工作空间运行时 API —— **UI 唯一的取数/改数入口**。
 *
 * 验收脚本 T1 会检查本对象的**方法集合**（页面上经 `window.__pwWorkspace`）：
 * 少一个方法 = UI 只能另找数据源 = 门禁变红。
 */
export const workspaceRuntime = {
  // ---- 一、读取（§一 / §二）----
  /** 当前工作空间。无工作空间时为 `null`。 */
  getCurrent: (): WorkspaceRuntime | null => getSnapshot(),
  /** 当前工作空间的应用列表。 */
  getApps: (): WorkspaceApp[] => getAppsSnapshot(),
  /** 当前工作空间的布局描述（`{type, snapshotId?}`）。 */
  getLayout: (): WorkspaceLayout | null => getLayoutMeta(),

  // ---- 二、状态（§二）----
  /** 更新某个应用的状态。返回变更后的应用；无工作空间或 appId 未知时返回 `null`。 */
  updateStatus: (appId: string, status: AppStatus): WorkspaceApp | null =>
    updateAppStatus(appId, status),

  // ---- 五、窗口事件（§五；为 TECH-03 预留）----
  /** 灌入一个窗口事件。当前只更新 Runtime，不连接真实软件。 */
  windowEvent: (input: WindowEventInput): WorkspaceApp | null => applyWindowEvent(input),
  /** 最近一次窗口事件（观察用）。 */
  lastWindowEvent,
  /** 当前焦点窗口标识。 */
  focusedWindowId,

  // ---- 三、布局快照（§三）----
  /** 采集当前 DOM 几何存为快照（并把 layout 标成 manual）。 */
  saveLayoutSnapshot,
  /** 恢复快照：写回 DOM + 把 layout 绑到该快照。 */
  loadLayoutSnapshot,
  /** 清除当前工作空间的快照，layout 回落 auto（DOM 复位由 UI 负责）。 */
  clearLayoutSnapshot,
  /** 按 id 取快照（只读）。 */
  getLayoutSnapshot,
  /** 列出当前工作空间的快照。 */
  listLayoutSnapshots,
  /** 把快照几何重放到 DOM（UI 在重渲染后可用）。 */
  applyLayoutToDom,

  // ---- 四、模板（§四）----
  /** 全部模板（含种子模板）。 */
  listTemplates: (): WorkspaceTemplate[] => listTemplates(),
  /** 按 id / 名称取模板。 */
  getTemplate: (idOrName: string): WorkspaceTemplate | null => findTemplate(idOrName),
  /**
   * 创建模板。`apps` 省略时取当前工作空间的应用；
   * `layoutSnapshot` 省略时现场采一份 DOM 几何快照（采不到则为 `null`）。
   */
  createTemplate: (input: CreateTemplateInput): WorkspaceTemplate => {
    const current = getSnapshot()
    const apps = input.apps ?? (current?.apps.map((a) => ({ appId: a.appId, name: a.name })) ?? [])
    if (!apps.length) throw new Error('创建模板需要一个应用列表（或先准备一个工作空间）')
    const snapshot =
      input.layoutSnapshot !== undefined ? input.layoutSnapshot : saveLayoutSnapshot()
    return addTemplate({
      id: newTemplateId(),
      name: input.name,
      goal: input.goal ?? '',
      apps: apps.map((a) => ({ appId: a.appId, name: a.name })),
      layoutSnapshot: snapshot,
    })
  },
  /** 把**当前工作空间**（应用 + DOM 几何快照）存成一个新模板（§四「保存模板」）。 */
  saveTemplate: (name?: string): WorkspaceTemplate | null => {
    const current = getSnapshot()
    if (!current) return null
    return workspaceRuntime.createTemplate({
      name: name ?? `${current.name} 模板`,
      goal: current.goal,
      apps: current.apps.map((a) => ({ appId: a.appId, name: a.name })),
    })
  },
  /** 按 id / 名称「加载模板」（§四）：注册其快照并把 layout 绑到当前工作空间。 */
  loadTemplate: (idOrName: string): WorkspaceTemplate | null => {
    const tpl = findTemplate(idOrName)
    if (!tpl) return null
    const snap = tpl.layoutSnapshot
    if (!snap) return tpl
    if (!findSnapshot(snap.snapshotId)) putSnapshot(snap)
    loadLayoutSnapshot(snap.snapshotId)
    return tpl
  },

  // ---- 六、准备流程（§六）----
  prepareWorkspace,
  /** prepare 流水线的固定步骤序列（顺序即契约；`prepareWorkspace` 的 report 必须与它逐项一致）。 */
  PREPARE_STEPS,

  // ---- 七、快照接入（TECH-04 §二）----
  /**
   * 快照能力：**只读视图 + 只算计划**。
   *
   * 本命名空间**没有任何"执行"入口** —— 不移动系统窗口、不杀进程、不改外部软件状态
   * （TECH-04 §二 的禁止项）。`restore()` 返回的每一步都带 `executable: false`；
   * 真正的窗口控制属后续阶段，接入时只需注入一个 `WindowProbe`。
   */
  snapshot: {
    /** 采集一份 v1 快照。未注入探针时恒 `dryRun: true`（**不编造数据**）。 */
    capture: (opts: CaptureOptions = {}): Promise<CaptureOutcome> =>
      captureSnapshot(injectedProbe ? { ...opts, probe: injectedProbe } : opts),
    /** 计算恢复计划（**只算不做**）。 */
    restore: (doc: unknown, opts: RestoreOptions = {}): RestorePlan => restoreSnapshot(doc, opts),
    /** 校验一份 v1 快照（与冻结契约同口径）。 */
    validate: (doc: unknown): SnapshotValidation => validateSnapshot(doc),
    /** 只读视图：当前工作空间状态 / 最近布局状态 / 恢复可用性。 */
    status: getRecoveryStatus,
    /** 接口是否已接通真实窗口探针（本轮恒 `false`）。 */
    isProbeWired: (): boolean => !!(injectedProbe && injectedProbe.wired),

    // ---- 注入点（真实采集接入时使用；本轮 UI 不注入，故恒为"未接线"）----
    /** 注入窗口探针。传 `null` 撤回 ⇒ 回到"未接线"（`capture()` 恢复 dryRun）。 */
    setProbe: (probe: WindowProbe | null): void => {
      injectedProbe = probe
    },
    /** 注入"已持久化 v1 快照"的读取器。**本层不碰 core**，读取由外部适配器提供。 */
    setPersistedReader: (fn: (() => unknown | null) | null): void => {
      persistedReader = fn
    },
    /** 告知当前 core 运行期标识（`null` = 未知 ⇒ 不判断 hwnd 是否失效）。 */
    setCurrentRunId: (id: string | null): void => {
      currentRunId = id
    },
  },

  // ---- 订阅 ----
  subscribe,
  getRevision,
}

/** 页面内调试 / 验收句柄（与 `window.__pwMotion` 同源做法）。 */
declare global {
  interface Window {
    __pwWorkspace?: typeof workspaceRuntime
  }
}

if (typeof window !== 'undefined') {
  window.__pwWorkspace = workspaceRuntime
}
