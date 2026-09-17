/**
 * Workspace Runtime Adapter —— Window Snapshot（TECH-07-C4）
 *
 * ## 职责边界（C4 §2 核心原则）
 * - **Facts 描述现在**（`facts.ts` 的实时快照 / `lastFacts` 运行时缓存）；
 * - **Snapshot 记录过去**（本文件 + Core config `workspace.snapshot.last`）；
 * - **Restore 只尝试让现在回到过去**，且每一步都重新校验。
 * 三者不合并：本文件**从不**把 `lastFacts` 当 snapshot，也**从不**把 snapshot 当 live facts。
 *
 * ## 冻结域关系
 * v1 契约与纯函数实现在 **TECH-02 冻结域** `ui/src/workspace/snapshot.ts`
 * （`capture()` / `restore()` / `validate()` / `WindowProbe` / `runId` 语义 / guardrails）。
 * C4 **不修改**它，只做：① 真实 `WindowProbe` 接线；② 经 Core config 持久化；
 * ③ 在冻结域之外执行受限 Restore（冻结域的 `restore()` 只产 plan，`executable` 恒 false）。
 *
 * ## 身份规则（C4 §5）
 * `WindowInfo` **没有** exePath。exePath 只能来自登记证据链：
 *   slots(sid→appId) ∪ apps_running(appId→pid) → apps_list → AppItem.path
 * 无证据 ⇒ 不进 snapshot（禁止用 title / 进程名 / hwnd 猜 exePath）。
 */

import { appsApi } from '@/api/appsService'
import { configApi } from '@/api/configService'
import { systemApi } from '@/api/systemService'
import {
  SNAPSHOT_CONFIG_KEY,
  capture as captureV1,
  validate as validateV1,
  restore as restoreV1,
} from '@/workspace/snapshot'
import type {
  SnapshotIssue,
  SnapshotSource,
  SnapshotWindowEntry,
  WindowProbe,
  WorkspaceSnapshotV1,
} from '@/workspace/snapshot'
import { snapshot as takeFacts, type WorkspaceFacts } from './facts'
import { placeWindow } from './actions'

// ---------------------------------------------------------------- 类型

export type CaptureStatus =
  | 'saved'
  | 'offline'
  | 'no_mode'
  | 'no_identity'
  | 'no_managed'
  | 'invalid'
  | 'write_failed'

export interface CaptureOutcome {
  status: CaptureStatus
  snapshotId: string | null
  /** 进入 managed 的窗口数（= 有 ownership + exePath 双重证据的窗口数）。 */
  managed: number
  runId: string | null
  issues: SnapshotIssue[]
  detail: string
}

export type RestoreSkipReason =
  | 'missing'
  | 'invalid'
  | 'ambiguous'
  | 'unowned'
  | 'offline'
  | 'placement_failed'
  | 'timeout'
  | 'skipped'

export interface RestoreItem {
  hwnd: number
  pid: number
  appId: number | null
  rect: { x: number; y: number; w: number; h: number }
  /** 拓扑修正标记：原 snapshot 坐标在当前工作区不可见，已做最小安全修正。 */
  adjusted: boolean
}

export interface RestoreSkip {
  hwnd?: number
  pid?: number
  appId?: number | null
  reason: RestoreSkipReason
  detail: string
}

export interface RestoreOutcome {
  ok: boolean
  status: 'restored' | 'partial' | 'nothing' | 'offline' | 'invalid' | 'no_snapshot'
  layer: 'same-run' | 'cross-restart' | 'none'
  snapshotId: string | null
  restored: RestoreItem[]
  skipped: RestoreSkip[]
  issues: SnapshotIssue[]
}

export interface SnapshotStatus {
  has: boolean
  valid: boolean
  snapshotId: string | null
  takenAt: number | null
  managed: number
  /** 快照所属 core 运行期；与 `currentRunId` 不同 ⇒ 旧 hwnd/pid 全部失效。 */
  snapshotRunId: string | null
  currentRunId: string | null
  sameRun: boolean
  issues: SnapshotIssue[]
}

/** 持久化读取结果（`invalid` = 结构损坏，必须拒绝且保留原值）。 */
type ReadResult =
  | { state: 'none' }
  | { state: 'valid'; snapshot: WorkspaceSnapshotV1 }
  | { state: 'invalid'; issues: SnapshotIssue[] }

interface Evidence {
  appId: number | null
  appName: string
  exePath: string | null
  exeName: string | null
}

/** 窗口至少要有这么大（拓扑修正下限；也防止 0 尺寸窗口）。 */
const MIN_VISIBLE = 32

// ---------------------------------------------------------------- 身份（runId / source）

/**
 * 当前 core 运行期 ID。
 *
 * 不是"虚构"的：它完全由 core 自报的两个真实事实组成（`pid` + `started_at`），
 * 因此同一次 core 生命周期内稳定、restart 后必变 —— 且**不写进 core 数据库**
 * （C4 §7：不要把它变成 Core 的新状态）。
 */
export async function currentRunId(): Promise<string | null> {
  const id = await systemApi.coreIdentity()
  if (!id) return null
  return `${id.pid}@${id.started_at}`
}

async function buildSource(): Promise<SnapshotSource | null> {
  const id = await systemApi.coreIdentity()
  if (!id) return null
  return {
    appVersion: systemApi.appVersion(),
    corePid: id.pid,
    runId: `${id.pid}@${id.started_at}`,
  }
}

// ---------------------------------------------------------------- ownership → exePath

/** pid → 登记证据（exePath 唯一来源：`apps_list` 的 `path`）。 */
async function buildEvidence(facts: WorkspaceFacts): Promise<Map<number, Evidence>> {
  const [apps, running] = await Promise.all([
    appsApi.list().catch(() => []),
    appsApi.running().catch(() => ({}) as Record<string, number>),
  ])
  const byId = new Map(apps.map((a) => [a.id, a]))
  const pidToAppId = new Map<number, number>()

  // 证据源 1：模式流水线 slots（pid + appId 同时给出）
  for (const s of facts.progress?.slots ?? []) {
    if (typeof s.pid === 'number' && s.pid > 0 && typeof s.appId === 'number' && s.appId > 0) {
      pidToAppId.set(s.pid, s.appId)
    }
  }
  // 证据源 2：core 运行注册表（appId → pid；slots 清空后仍成立）
  for (const [appId, pid] of Object.entries(running)) {
    const p = Number(pid)
    const a = Number(appId)
    if (Number.isInteger(p) && p > 0 && Number.isInteger(a) && a > 0) pidToAppId.set(p, a)
  }

  const out = new Map<number, Evidence>()
  for (const [pid, appId] of pidToAppId) {
    const app = byId.get(appId)
    const exePath = app?.path && app.path.trim() ? app.path : null
    out.set(pid, {
      appId,
      appName: app?.name ?? '',
      exePath,
      exeName: exePath ? exePath.split(/[\\/]/).pop() ?? null : null,
    })
  }
  return out
}

// ---------------------------------------------------------------- 探针（真实 facts → v1 结构）

function buildProbe(
  facts: WorkspaceFacts,
  evidence: Map<number, Evidence>,
  source: SnapshotSource,
  modeId: number,
): WindowProbe {
  const monitors = facts.monitors.map((m) => ({
    index: m.index,
    primary: m.primary,
    bounds: { x: m.x, y: m.y, w: m.w, h: m.h },
    work: { x: m.work_x, y: m.work_y, w: m.work_w, h: m.work_h },
  }))
  const fallbackIndex = monitors.find((m) => m.primary)?.index ?? monitors[0]?.index ?? 0
  const monitorOf = (r: { x: number; y: number; w: number; h: number }): number => {
    const cx = r.x + r.w / 2
    const cy = r.y + r.h / 2
    const hit = monitors.find(
      (m) => cx >= m.bounds.x && cx < m.bounds.x + m.bounds.w && cy >= m.bounds.y && cy < m.bounds.y + m.bounds.h,
    )
    return hit ? hit.index : fallbackIndex
  }

  // 只收录 ownership-confirmed + 有 exePath 证据的窗口（两者缺一即不进快照）
  const owned = facts.windows.filter((w) => w.belongsToMode && w.manageable && w.rect)
  const entries: SnapshotWindowEntry[] = []
  owned.forEach((w) => {
    const ev = evidence.get(w.pid)
    if (!ev?.exePath || !ev.exeName) return // 无 exePath 证据 ⇒ 不快照（禁止伪造）
    const rect = w.rect as { x: number; y: number; w: number; h: number }
    const mon = monitors.find((m) => m.index === monitorOf(rect)) ?? monitors[0]
    entries.push({
      hwnd: w.hwnd,
      pid: w.pid,
      exeName: ev.exeName,
      exePath: ev.exePath,
      appId: ev.appId,
      title: (w.title ?? '').slice(0, 120),
      className: w.className ?? '',
      monitorIndex: mon?.index ?? fallbackIndex,
      rectPx: { x: rect.x, y: rect.y, w: rect.w, h: rect.h },
      // capture() 会按 deriveNormRect 重算一遍（保证 rectNorm 一致性不变量），此处先给占位
      rectNorm: { x: 0, y: 0, w: 0, h: 0 },
      // windows_list 已过滤"可见 + 非工具窗"；minimized/maximized 来自 core 真实位
      state: {
        visible: true,
        minimized: w.state === 'minimized',
        maximized: w.state === 'maximized',
      },
      zIndex: entries.length + 1, // 枚举序近似 Z 序（C4-D3 诚实降级，非真实 Z 序）
    })
  })

  const managed = entries.map((w) => ({
    appId: w.appId,
    appName: evidence.get(w.pid)?.appName ?? w.exeName,
    pid: w.pid,
    hwnd: w.hwnd,
  }))

  return {
    wired: true,
    source: () => Promise.resolve(source),
    monitors: () => Promise.resolve(monitors),
    windows: () => Promise.resolve(entries),
    foregroundHwnd: () => Promise.resolve(null), // C4-D3：无真实前台事实 ⇒ null，不猜
    workspace: () =>
      Promise.resolve({
        modeName: facts.mode.running ?? '',
        modeId,
        layoutName: facts.mode.layout ?? null,
        monitor: fallbackIndex,
        launchedAppIds: facts.mode.apps
          .map((a) => a.appId)
          .filter((v): v is number => typeof v === 'number'),
        managed,
      }),
  }
}

// ---------------------------------------------------------------- Capture

/** 捕获 + 校验 + 原子写入 Core config（任一步失败都**不覆盖**已有快照）。 */
export async function captureSnapshot(): Promise<CaptureOutcome> {
  const fail = (status: CaptureStatus, detail: string, extra: Partial<CaptureOutcome> = {}): CaptureOutcome => ({
    status,
    snapshotId: null,
    managed: 0,
    runId: null,
    issues: [],
    detail,
    ...extra,
  })

  // 1) 新鲜事实（**不用** lastSnapshot —— 那是运行时缓存，不是事实源）
  let facts: WorkspaceFacts
  try {
    facts = await takeFacts()
  } catch (e) {
    return fail('offline', `事实拉取失败：${String((e as Error)?.message ?? e)}`)
  }
  if (facts.connectivity === 'offline') {
    // C4 §10：core 不可用 ⇒ 不得写入空快照覆盖最后一份有效快照
    return fail('offline', 'core 未连接 —— 不写入快照（保留上次有效快照）')
  }

  // 2) 当前模式（v1 trigger 只有 enter_mode；不在模式里就没有"工作区状态"可言）
  const modeName = facts.mode.running
  const modeId = modeName ? (facts.modes.find((m) => m.name === modeName)?.id ?? 0) : 0
  if (!modeName || !modeId) return fail('no_mode', '当前不在任何工作模式中（v1 仅 enter_mode 触发）')

  // 3) 真实 source（core 自报事实，拿不到就不写 —— 不编造 pid/runId）
  const source = await buildSource()
  if (!source) return fail('no_identity', '无法取得 core 身份事实（pid/启动时间）—— 不写快照')

  // 4) 真实探针 → 冻结域 capture（内部已跑 validate）
  const evidence = await buildEvidence(facts)
  const probe = buildProbe(facts, evidence, source, modeId)
  const res = await captureV1({ probe })
  if (!res.ok || !res.snapshot) {
    return fail('invalid', 'capture 校验未通过（不覆盖已有快照）', { issues: res.issues })
  }
  const snap = res.snapshot
  if (!snap.workspace.managed.length) {
    return fail('no_managed', '没有带归属证据的窗口（空快照不覆盖已有有效快照）')
  }

  // 5) 原子写入：Core config 单键覆盖（成功即已落库；失败即未落库，不存在"半写"）
  try {
    await configApi.putCore(SNAPSHOT_CONFIG_KEY, snap)
  } catch (e) {
    return fail('write_failed', `Core config 写入失败：${String((e as Error)?.message ?? e)}`, {
      issues: res.issues,
    })
  }
  return {
    status: 'saved',
    snapshotId: snap.snapshotId,
    managed: snap.workspace.managed.length,
    runId: source.runId,
    issues: [],
    detail: `已保存 ${snap.workspace.managed.length} 个受管窗口（runId=${source.runId}）`,
  }
}

// ---------------------------------------------------------------- Read / Status

async function readSnapshot(): Promise<ReadResult> {
  let raw: unknown
  try {
    raw = await configApi.getCore<unknown>(SNAPSHOT_CONFIG_KEY)
  } catch {
    return { state: 'none' }
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).length === 0) {
    return { state: 'none' } // 默认 {} = 从未写过
  }
  const v = validateV1(raw)
  return v.ok ? { state: 'valid', snapshot: raw as WorkspaceSnapshotV1 } : { state: 'invalid', issues: v.issues }
}

/** 快照状态投影（UI / 验收消费；不做任何写入）。 */
export async function getSnapshotStatus(): Promise<SnapshotStatus> {
  const [read, runId] = await Promise.all([readSnapshot(), currentRunId()])
  if (read.state === 'invalid') {
    return {
      has: true,
      valid: false,
      snapshotId: null,
      takenAt: null,
      managed: 0,
      snapshotRunId: null,
      currentRunId: runId,
      sameRun: false,
      issues: read.issues,
    }
  }
  if (read.state === 'none') {
    return {
      has: false,
      valid: false,
      snapshotId: null,
      takenAt: null,
      managed: 0,
      snapshotRunId: null,
      currentRunId: runId,
      sameRun: false,
      issues: [],
    }
  }
  const s = read.snapshot
  return {
    has: true,
    valid: true,
    snapshotId: s.snapshotId,
    takenAt: s.takenAt,
    managed: s.workspace.managed.length,
    snapshotRunId: s.source.runId,
    currentRunId: runId,
    sameRun: runId !== null && runId === s.source.runId,
    issues: [],
  }
}

// ---------------------------------------------------------------- 拓扑安全

/**
 * 最小安全修正：把 snapshot 的物理 rect 拉回当前主显示器工作区 —— **完整可见**。
 *
 * 只动位置、不改尺寸（"最小修正"）：窗口能放下就整窗推进工作区；
 * 只有在"工作区比窗口还小"这种极端情况下才退化为"至少 MIN_VISIBLE 像素可见"
 * （不把窗口推到完全看不见的地方）。不做多显示器系统、不做智能布局（C4 §19）。
 */
export function safeRect(
  rect: { x: number; y: number; w: number; h: number },
  wa: { x: number; y: number; w: number; h: number },
): { rect: { x: number; y: number; w: number; h: number }; adjusted: boolean } {
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
  const w = clamp(Math.round(rect.w) || MIN_VISIBLE, MIN_VISIBLE, Math.max(MIN_VISIBLE, wa.w))
  const h = clamp(Math.round(rect.h) || MIN_VISIBLE, MIN_VISIBLE, Math.max(MIN_VISIBLE, wa.h))
  // 装得下 ⇒ 整窗进工作区（右/下边界 = 工作区边界 - 窗口尺寸）；
  // 装不下（工作区比窗口还小）⇒ 退化成"至少 MIN_VISIBLE 像素可见"。
  const xLo = w <= wa.w ? wa.x : wa.x - w + MIN_VISIBLE
  const xHi = w <= wa.w ? wa.x + wa.w - w : wa.x + wa.w - MIN_VISIBLE
  const yLo = h <= wa.h ? wa.y : wa.y - h + MIN_VISIBLE
  const yHi = h <= wa.h ? wa.y + wa.h - h : wa.y + wa.h - MIN_VISIBLE
  const x = clamp(Math.round(rect.x), xLo, xHi)
  const y = clamp(Math.round(rect.y), yLo, yHi)
  const out = { x, y, w, h }
  const adjusted = out.x !== Math.round(rect.x) || out.y !== Math.round(rect.y) || out.w !== Math.round(rect.w) || out.h !== Math.round(rect.h)
  return { rect: out, adjusted }
}

function primaryWorkArea(facts: WorkspaceFacts): { x: number; y: number; w: number; h: number } | null {
  const m = facts.monitors.find((x) => x.primary) ?? facts.monitors[0]
  if (!m || m.work_w <= 0 || m.work_h <= 0) return null
  return { x: m.work_x, y: m.work_y, w: m.work_w, h: m.work_h }
}

// ---------------------------------------------------------------- Restore

export interface RestoreOptions {
  /** 整体超时（ms）。0/缺省 = 10s。每个候选都受它约束，绝无无限等待。 */
  timeoutMs?: number
}

/**
 * 受限恢复：Snapshot → 重新校验 → windows_place → 真实外部窗口。
 *
 * - 失败分窗口记账（missing / invalid / ambiguous / unowned / offline /
 *   placement_failed / timeout / skipped），单窗失败不影响其它窗口；
 * - 绝不启动软件、绝不杀进程/关窗、绝不 `windows_activate`（focus 步骤全部 skip）；
 * - 最小化窗口 skip（C4-D4）；
 * - core offline ⇒ 零 actuation。
 */
export async function restoreSnapshot(opts: RestoreOptions = {}): Promise<RestoreOutcome> {
  const timeoutMs = opts.timeoutMs && opts.timeoutMs > 0 ? opts.timeoutMs : 10_000
  const deadline = Date.now() + timeoutMs

  // 1) 新鲜事实 + 连通性（offline ⇒ 直接 fail-closed，零 actuation）
  let facts: WorkspaceFacts
  try {
    facts = await takeFacts()
  } catch (e) {
    return {
      ok: false,
      status: 'offline',
      layer: 'none',
      snapshotId: null,
      restored: [],
      skipped: [{ reason: 'offline', detail: `事实拉取失败：${String((e as Error)?.message ?? e)}` }],
      issues: [],
    }
  }
  if (facts.connectivity === 'offline') {
    return {
      ok: false,
      status: 'offline',
      layer: 'none',
      snapshotId: null,
      restored: [],
      skipped: [{ reason: 'offline', detail: 'core 未连接 —— 不执行任何摆位' }],
      issues: [],
    }
  }

  // 2) 读快照（损坏 ⇒ 拒绝 + 保留原值，零 actuation）
  const read = await readSnapshot()
  if (read.state === 'none') {
    return { ok: true, status: 'no_snapshot', layer: 'none', snapshotId: null, restored: [], skipped: [], issues: [] }
  }
  if (read.state === 'invalid') {
    return {
      ok: false,
      status: 'invalid',
      layer: 'none',
      snapshotId: null,
      restored: [],
      skipped: [{ reason: 'invalid', detail: `快照校验失败（保留原快照）：${read.issues.length} 项问题` }],
      issues: read.issues,
    }
  }

  const snap = read.snapshot
  const wa = primaryWorkArea(facts)
  if (!wa) {
    return {
      ok: false,
      status: 'invalid',
      layer: 'none',
      snapshotId: snap.snapshotId,
      restored: [],
      skipped: [{ reason: 'invalid', detail: '当前主显示器工作区不可用' }],
      issues: [],
    }
  }

  const runId = await currentRunId()
  const sameRun = runId !== null && runId === snap.source.runId
  const evidence = await buildEvidence(facts)
  const byHwnd = new Map(snap.desktop.windows.map((w) => [w.hwnd, w]))
  const restored: RestoreItem[] = []
  const skipped: RestoreSkip[] = []

  // 3) 候选集（只可能是"当前已归属"的窗口 —— 禁止全系统按 exe 搜）
  const ownedNow = facts.windows.filter((w) => w.belongsToMode && w.manageable && w.rect)
  const exeOf = (w: { pid: number }): string | null => evidence.get(w.pid)?.exePath ?? null

  type Target = { entry: SnapshotWindowEntry; hwnd: number; pid: number }
  const targets: Target[] = []

  if (sameRun) {
    // ---- Layer 1：hwnd + pid 直接身份（复用冻结域 restore() 的 plan 作为 intent）
    const plan = restoreV1(snap, { currentRunId: runId ?? undefined })
    for (const step of plan.steps) {
      if (step.kind === 'focus-window') {
        skipped.push({ hwnd: step.hwnd, reason: 'skipped', detail: 'focus-window：C4 不恢复前台焦点' })
        continue
      }
      if (step.kind === 'skip') {
        skipped.push({
          hwnd: step.hwnd,
          pid: step.pid,
          appId: step.appId ?? null,
          reason: 'skipped',
          detail: step.reason,
        })
        continue
      }
      if (step.hwnd === undefined || step.pid === undefined) {
        skipped.push({ reason: 'invalid', detail: step.reason || 'plan 缺少 hwnd/pid' })
        continue
      }
      // 重新校验：窗口仍存在 + 仍归属 + pid 未变（§12：不得仅凭快照 hwnd 操作）
      const live = facts.windows.find((w) => w.hwnd === step.hwnd)
      if (!live) {
        skipped.push({ hwnd: step.hwnd, pid: step.pid, reason: 'missing', detail: '窗口已不存在' })
        continue
      }
      if (live.pid !== step.pid) {
        skipped.push({ hwnd: step.hwnd, pid: step.pid, reason: 'unowned', detail: `hwnd 对应的 pid 已变（${step.pid} → ${live.pid}）` })
        continue
      }
      if (!live.belongsToMode || !live.manageable) {
        skipped.push({ hwnd: step.hwnd, pid: step.pid, reason: 'unowned', detail: '窗口不再属于当前工作模式' })
        continue
      }
      const entry = byHwnd.get(step.hwnd)
      if (!entry) {
        skipped.push({ hwnd: step.hwnd, pid: step.pid, reason: 'invalid', detail: '快照缺少该窗口条目' })
        continue
      }
      targets.push({ entry, hwnd: live.hwnd, pid: live.pid })
    }
  } else {
    // ---- Layer 2：跨重启 —— 旧 hwnd/pid 全部失效，只按 exePath 在"已归属窗口"里找唯一候选
    for (const entry of snap.desktop.windows) {
      if (!entry.exePath) {
        skipped.push({ appId: entry.appId, reason: 'invalid', detail: '快照条目无 exePath，无法跨重启识别' })
        continue
      }
      const candidates = ownedNow.filter((w) => exeOf(w) !== null && exeOf(w) === entry.exePath)
      if (candidates.length === 0) {
        skipped.push({ appId: entry.appId, reason: 'missing', detail: `当前无受管窗口匹配 exePath：${entry.exePath}` })
        continue
      }
      if (candidates.length > 1) {
        skipped.push({
          appId: entry.appId,
          reason: 'ambiguous',
          detail: `同 exePath 存在 ${candidates.length} 个候选（不猜，skip）`,
        })
        continue
      }
      const only = candidates[0]!
      targets.push({ entry, hwnd: only.hwnd, pid: only.pid })
    }
  }

  // 4) 逐窗执行（每次都重新校验 + 超时保护）
  for (const t of targets) {
    if (Date.now() > deadline) {
      skipped.push({ hwnd: t.hwnd, pid: t.pid, appId: t.entry.appId, reason: 'timeout', detail: `超出 ${timeoutMs}ms 预算` })
      continue
    }
    // 最小化窗口：C4-D4 skip（不激活、不还原、不改状态）
    if (t.entry.state.minimized) {
      skipped.push({ hwnd: t.hwnd, pid: t.pid, appId: t.entry.appId, reason: 'skipped', detail: '最小化窗口：C4 不恢复/不激活' })
      continue
    }
    // 执行前最后一次校验：仍然在实时事实里且仍归属
    const live = facts.windows.find((w) => w.hwnd === t.hwnd && w.pid === t.pid)
    if (!live || !live.belongsToMode || !live.manageable) {
      skipped.push({ hwnd: t.hwnd, pid: t.pid, appId: t.entry.appId, reason: 'unowned', detail: '执行前校验失败：窗口已不归属/不存在' })
      continue
    }
    const { rect, adjusted } = safeRect(t.entry.rectPx, wa)
    // 物理 px → 归一化意图（与 C3 placeWindow 同一换算口径）
    const intent = {
      hwnd: t.hwnd,
      x: (rect.x - wa.x) / wa.w,
      y: (rect.y - wa.y) / wa.h,
      w: rect.w / wa.w,
      h: rect.h / wa.h,
    }
    const res = await placeWindow(intent, wa)
    if (res.status === 'placed') {
      restored.push({ hwnd: t.hwnd, pid: t.pid, appId: t.entry.appId, rect, adjusted })
      continue
    }
    const reason: RestoreSkipReason =
      res.status === 'unbound' ? 'unowned' : res.status === 'offline' ? 'offline' : 'placement_failed'
    skipped.push({
      hwnd: t.hwnd,
      pid: t.pid,
      appId: t.entry.appId,
      reason,
      detail: res.message ?? res.status,
    })
  }

  const status: RestoreOutcome['status'] =
    restored.length > 0 ? (skipped.length > 0 ? 'partial' : 'restored') : 'nothing'
  return {
    ok: true,
    status,
    layer: sameRun ? 'same-run' : 'cross-restart',
    snapshotId: snap.snapshotId,
    restored,
    skipped,
    issues: [],
  }
}

export const windowSnapshot = {
  captureSnapshot,
  restoreSnapshot,
  getSnapshotStatus,
  currentRunId,
}
