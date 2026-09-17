/**
 * WorkspaceSnapshot v1 —— 接真实窗口前的**接口准备**（TECH-03-B §三）
 *
 * ## 这一层是什么 / 不是什么
 * 这是 `workspace.snapshot.last`（PW-INTEGRATION-003 冻结契约）在**前端侧的接口面**：
 * 三个方法 `capture()` / `restore()` / `validate()`，
 * 与 `docs/contracts/workspace-snapshot.v1.schema.json` **同一条口径**。
 *
 * **本轮明确不做**（TECH-03-B §三 的禁止项，逐条落在代码上）：
 * - ❌ 不杀进程 —— 全模块没有 `kill`/`terminate` 之类的调用路径；
 * - ❌ 不启动软件 —— 缺窗口只产出 `skip` 计划步骤，**绝不**变成"帮我把它拉起来"；
 * - ❌ 不改数据库 —— 本模块零 import（不碰 store / @/api / core），纯函数；
 * - ❌ 不做窗口控制 —— `restore()` **只算计划，不执行**（每步 `executable: false`）。
 *
 * 因此它能在 Node 里被直接编译执行 —— 验收脚本就是这么验它（与 TECH-03-A 同法）。
 *
 * ## 为什么 hwnd 不能跨重启用
 * 契约写明：`hwnd` 是 **volatile**，只在 `source.runId`（本次 core 运行期）内有效。
 * 换 runId 即视为**全部 hwnd 失效**，`restore()` 会把每步降级成 `skip` 并说明原因 ——
 * 而不是假装能按旧 hwnd 恢复。这条是本模块最重要的一条语义。
 *
 * ## 字段（未来真实窗口需要的四件）
 * `hwnd`（句柄）· `pid`（进程）· `rectPx`/`rectNorm`（位置尺寸）· `zIndex`（Z 序，越大越靠前）
 * —— 都已在 `SnapshotWindowEntry` 里定稿，接真实采集时不需要改结构。
 */

/** 契约版本（`const: 1`，v2 字段进不来）。 */
export const SNAPSHOT_SCHEMA_VERSION = 1

/** 持久化落点：core config 键。**唯一写入者是 core**，前端只读/只组装。 */
export const SNAPSHOT_CONFIG_KEY = 'workspace.snapshot.last'

/** v1 只允许这一种写入触发（A→B 模式切换**不写**持久快照）。 */
export const SNAPSHOT_TRIGGERS = ['enter_mode'] as const

/**
 * v2 越界字段黑名单（与 schema 的 `x-pw-v2-forbidden` 一字不差）。
 * 任何"顺手加个历史/多份/跨重启身份映射"的改动都会在这里被拦下。
 */
export const SNAPSHOT_V2_FORBIDDEN: readonly string[] = [
  'history',
  'snapshots',
  'snapshotHistory',
  'previousSnapshots',
  'multiSnapshot',
  'hwndIdentity',
  'windowIdentityMap',
  'restoreCount',
  'restoreLog',
  'keepAliveRegistry',
]

/** 归一化坐标一致性容差（与 `tools/verify_contracts.py` 的 NORM_TOL 一致）。 */
export const NORM_TOLERANCE = 0.02

/** 明文密钥键名特征（红线 V1：契约/配置/日志都不得出现明文）。 */
const SECRET_KEY_RE = /(api[_-]?key|secret|token|password|passwd|credential|bearer|private[_-]?key|sk-)/i

/** `snapshotId` 形态：`ws-YYYYMMDD-HHMMSS-xxxx`（与 schema 的 pattern 一致）。 */
export const SNAPSHOT_ID_RE = /^ws-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$/

// ---------------------------------------------------------------- 结构定义

export interface PxRect {
  x: number
  y: number
  w: number
  h: number
}

/** 相对所属显示器 `work` 区的归一化坐标（0~1）。 */
export interface NormRect {
  x: number
  y: number
  w: number
  h: number
}

export interface SnapshotWindowState {
  visible: boolean
  minimized: boolean
  maximized: boolean
}

export interface SnapshotMonitor {
  index: number
  primary: boolean
  /** 显示器全幅（物理像素）。 */
  bounds: PxRect
  /** 工作区（不含任务栏）。`rectNorm` 的换算基准。 */
  work: PxRect
}

/**
 * 一个被快照的**系统窗口**。
 *
 * 四个关键字段（本轮"接口准备"要确认未来能支持的就是它们）：
 * - `hwnd` —— 句柄，volatile（仅 `source.runId` 期间有效）
 * - `pid` —— 进程 id
 * - `rectPx` / `rectNorm` —— 位置尺寸（绝对像素 + 归一化）
 * - `zIndex` —— EnumWindows 返回序的近似 Z 序，越大越靠前
 */
export interface SnapshotWindowEntry {
  hwnd: number
  pid: number
  exeName: string
  exePath: string | null
  appId: number | null
  title: string
  className: string
  monitorIndex: number
  rectPx: PxRect
  rectNorm: NormRect
  state: SnapshotWindowState
  zIndex: number
}

/** 模式布局接管过的窗口（退出时收尾对象）。 */
export interface SnapshotManagedEntry {
  appId: number | null
  appName: string
  pid: number | null
  hwnd: number | null
}

export interface SnapshotSource {
  appVersion: string
  corePid: number
  /** 本次 core 运行期唯一标识 —— hwnd 有效性边界。 */
  runId: string
}

export interface SnapshotWorkspaceContext {
  modeName: string
  modeId: number
  layoutName: string | null
  monitor: number
  launchedAppIds: number[]
  managed: SnapshotManagedEntry[]
}

export interface WorkspaceSnapshotV1 {
  schemaVersion: 1
  snapshotId: string
  takenAt: number
  trigger: (typeof SNAPSHOT_TRIGGERS)[number]
  source: SnapshotSource
  monitors: SnapshotMonitor[]
  desktop: {
    foregroundHwnd: number | null
    windows: SnapshotWindowEntry[]
  }
  workspace: SnapshotWorkspaceContext
}

export interface SnapshotIssue {
  /** 与 `tools/verify_contracts.py` 同形的路径（`$.desktop.windows[0].rectNorm`）。 */
  path: string
  /** 错误签名，如 `invariant:rectNorm-consistent` / `required:exeName`。 */
  code: string
  message: string
}

export interface SnapshotValidation {
  ok: boolean
  issues: SnapshotIssue[]
}

// ---------------------------------------------------------------- 小工具

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function isInt(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v)
}

/** 采集侧唯一的归一化换算实现（避免调用方各写一遍导致 rectNorm 不一致）。 */
export function deriveNormRect(rectPx: PxRect, work: PxRect): NormRect {
  const w = work.w || 1
  const h = work.h || 1
  const round = (n: number): number => Math.round(n * 10000) / 10000
  return {
    x: round((rectPx.x - work.x) / w),
    y: round((rectPx.y - work.y) / h),
    w: round(rectPx.w / w),
    h: round(rectPx.h / h),
  }
}

/** 生成一个符合契约 pattern 的 snapshotId。 */
export function makeSnapshotId(at: number, suffix: string): string {
  const d = new Date(at)
  const p = (n: number, len = 2): string => String(n).padStart(len, '0')
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(
    d.getMinutes(),
  )}${p(d.getSeconds())}`
  const hex = suffix.toLowerCase().replace(/[^0-9a-f]/g, '').padEnd(4, '0').slice(0, 4)
  return `ws-${stamp}-${hex}`
}

// ---------------------------------------------------------------- validate()

function checkRect(
  node: unknown,
  path: string,
  issues: SnapshotIssue[],
  opts: { normalized: boolean },
): void {
  if (!isPlainObject(node)) {
    issues.push({ path, code: 'type:object', message: `${path} 必须是对象` })
    return
  }
  const keys = opts.normalized ? ['x', 'y', 'w', 'h'] : ['x', 'y', 'w', 'h']
  for (const k of keys) {
    const v = node[k]
    if (opts.normalized) {
      if (typeof v !== 'number' || Number.isNaN(v)) {
        issues.push({ path: `${path}.${k}`, code: 'type:number', message: `${k} 必须是数字` })
        continue
      }
      if (v < 0 || v > 1) {
        issues.push({
          path: `${path}.${k}`,
          code: 'range:0-1',
          message: `归一化坐标必须在 0~1：${k}=${v}`,
        })
      }
    } else {
      if (!isInt(v)) {
        issues.push({ path: `${path}.${k}`, code: 'type:integer', message: `${k} 必须是整数` })
        continue
      }
      if ((k === 'w' || k === 'h') && (v as number) < 1) {
        issues.push({
          path: `${path}.${k}`,
          code: 'minimum:1',
          message: `宽高必须 ≥ 1：${k}=${v}`,
        })
      }
    }
  }
  for (const k of Object.keys(node)) {
    if (!keys.includes(k)) {
      issues.push({ path, code: `unexpected-key:${k}`, message: `${path} 不允许字段 ${k}` })
    }
  }
}

/** v2 越界字段 + 明文密钥（全树扫描）。 */
function scanTree(node: unknown, path: string, issues: SnapshotIssue[]): void {
  if (isPlainObject(node)) {
    for (const [key, child] of Object.entries(node)) {
      if (SNAPSHOT_V2_FORBIDDEN.includes(key)) {
        issues.push({
          path,
          code: `forbidden-v2-key:${key}`,
          message: `v1 不允许出现 v2 字段「${key}」（history 类字段属 v2 范围）`,
        })
      }
      if (SECRET_KEY_RE.test(key)) {
        issues.push({
          path,
          code: `secret-key:${key}`,
          message: `契约里不允许出现密钥字段「${key}」（红线 V1）`,
        })
      }
      scanTree(child, `${path}.${key}`, issues)
    }
    return
  }
  if (Array.isArray(node)) {
    node.forEach((child, i) => scanTree(child, `${path}[${i}]`, issues))
  }
}

function checkWindowEntry(w: unknown, i: number, issues: SnapshotIssue[]): void {
  const path = `$.desktop.windows[${i}]`
  if (!isPlainObject(w)) {
    issues.push({ path, code: 'type:object', message: `${path} 必须是对象` })
    return
  }
  const required = [
    'hwnd',
    'pid',
    'exeName',
    'exePath',
    'appId',
    'title',
    'className',
    'monitorIndex',
    'rectPx',
    'rectNorm',
    'state',
    'zIndex',
  ]
  for (const k of required) {
    if (!(k in w)) issues.push({ path, code: `required:${k}`, message: `缺少必填字段 ${k}` })
  }
  for (const k of Object.keys(w)) {
    if (!required.includes(k)) {
      issues.push({ path, code: `unexpected-key:${k}`, message: `不允许字段 ${k}` })
    }
  }
  for (const k of ['hwnd', 'pid', 'zIndex', 'monitorIndex'] as const) {
    const v = w[k]
    if (!isInt(v)) {
      issues.push({ path: `${path}.${k}`, code: 'type:integer', message: `${k} 必须是整数` })
    } else if (k !== 'monitorIndex' && v < 1) {
      issues.push({ path: `${path}.${k}`, code: 'minimum:1', message: `${k} 必须 ≥ 1` })
    } else if (k === 'monitorIndex' && v < 0) {
      issues.push({ path: `${path}.${k}`, code: 'minimum:0', message: 'monitorIndex 必须 ≥ 0' })
    }
  }
  if (typeof w.exeName !== 'string' || !w.exeName) {
    issues.push({ path: `${path}.exeName`, code: 'minLength:1', message: 'exeName 不能为空' })
  }
  if (typeof w.title !== 'string' || w.title.length > 120) {
    issues.push({ path: `${path}.title`, code: 'maxLength:120', message: 'title 必须 ≤ 120 字符' })
  }
  if (typeof w.className !== 'string') {
    issues.push({ path: `${path}.className`, code: 'type:string', message: 'className 必须是字符串' })
  }
  if (w.exePath !== null && typeof w.exePath !== 'string') {
    issues.push({
      path: `${path}.exePath`,
      code: 'type:string|null',
      message: 'exePath 必须是字符串或 null',
    })
  }
  if (w.appId !== null && !isInt(w.appId)) {
    issues.push({
      path: `${path}.appId`,
      code: 'type:integer|null',
      message: 'appId 必须是整数或 null',
    })
  }
  checkRect(w.rectPx, `${path}.rectPx`, issues, { normalized: false })
  checkRect(w.rectNorm, `${path}.rectNorm`, issues, { normalized: true })

  const st = w.state
  if (!isPlainObject(st)) {
    issues.push({ path: `${path}.state`, code: 'type:object', message: 'state 必须是对象' })
  } else {
    for (const k of ['visible', 'minimized', 'maximized']) {
      if (typeof st[k] !== 'boolean') {
        issues.push({
          path: `${path}.state.${k}`,
          code: 'type:boolean',
          message: `state.${k} 必须是布尔值`,
        })
      }
    }
    for (const k of Object.keys(st)) {
      if (!['visible', 'minimized', 'maximized'].includes(k)) {
        issues.push({ path: `${path}.state`, code: `unexpected-key:${k}`, message: `不允许字段 ${k}` })
      }
    }
  }
}

function checkMonitors(monitors: unknown, issues: SnapshotIssue[]): void {
  const path = '$.monitors'
  if (!Array.isArray(monitors)) {
    issues.push({ path, code: 'type:array', message: 'monitors 必须是数组' })
    return
  }
  if (monitors.length < 1) {
    issues.push({ path, code: 'minItems:1', message: '至少要有 1 个显示器' })
  }
  if (monitors.length > 8) {
    issues.push({ path, code: 'maxItems:8', message: 'monitors 最多 8 项' })
  }
  monitors.forEach((m, i) => {
    const mp = `${path}[${i}]`
    if (!isPlainObject(m)) {
      issues.push({ path: mp, code: 'type:object', message: `${mp} 必须是对象` })
      return
    }
    for (const k of ['index', 'primary', 'bounds', 'work']) {
      if (!(k in m)) issues.push({ path: mp, code: `required:${k}`, message: `缺少必填字段 ${k}` })
    }
    for (const k of Object.keys(m)) {
      if (!['index', 'primary', 'bounds', 'work'].includes(k)) {
        issues.push({ path: mp, code: `unexpected-key:${k}`, message: `不允许字段 ${k}` })
      }
    }
    if (!isInt(m.index) || m.index < 0) {
      issues.push({ path: `${mp}.index`, code: 'type:integer', message: 'index 必须是非负整数' })
    }
    if (typeof m.primary !== 'boolean') {
      issues.push({ path: `${mp}.primary`, code: 'type:boolean', message: 'primary 必须是布尔值' })
    }
    checkRect(m.bounds, `${mp}.bounds`, issues, { normalized: false })
    checkRect(m.work, `${mp}.work`, issues, { normalized: false })
  })
}

/**
 * 跨字段不变量（schema 表达不了的部分，与 `tools/verify_contracts.py::snapshot_invariants` 同口径）：
 * 显示器序号连续且恰有 1 个 primary、窗口的 monitorIndex 必须存在、
 * rectNorm 必须与 rectPx/work 一致、hwnd 唯一、前台窗口必须在列表内、
 * workspace.monitor 必须存在、managed 里的 hwnd 必须是 windows 的子集。
 */
function checkInvariants(doc: WorkspaceSnapshotV1, issues: SnapshotIssue[]): void {
  const monitors = doc.monitors as unknown
  if (!Array.isArray(monitors)) return

  const idxs = monitors
    .filter(isPlainObject)
    .map((m) => m.index)
    .filter(isInt)
    .sort((a, b) => a - b)
  if (idxs.length !== monitors.length || idxs.some((v, i) => v !== i)) {
    issues.push({ path: '$', code: 'invariant:monitors-index', message: '显示器 index 必须是 0..n-1' })
  }
  if (monitors.filter((m) => isPlainObject(m) && m.primary === true).length !== 1) {
    issues.push({ path: '$', code: 'invariant:monitors-primary', message: '必须恰有 1 个 primary 显示器' })
  }

  const byIndex = new Map<number, Record<string, unknown>>()
  for (const m of monitors) {
    if (isPlainObject(m) && isInt(m.index)) byIndex.set(m.index, m)
  }

  const windows = doc.desktop?.windows
  if (!Array.isArray(windows)) return

  const seenHwnd = new Set<number>()
  windows.forEach((w, i) => {
    if (!isPlainObject(w)) return
    const wp = `$.desktop.windows[${i}]`
    const mi = w.monitorIndex
    if (!isInt(mi) || !byIndex.has(mi)) {
      issues.push({ path: wp, code: 'invariant:monitorIndex-exists', message: 'monitorIndex 指向不存在的显示器' })
      return
    }
    const work = (byIndex.get(mi)?.work ?? {}) as Partial<PxRect>
    const px = w.rectPx as PxRect | undefined
    const norm = w.rectNorm as NormRect | undefined
    if (px && norm && work.w && work.h) {
      const expected = deriveNormRect(px, work as PxRect)
      const keys: (keyof NormRect)[] = ['x', 'y', 'w', 'h']
      const drift = keys.some((k) => Math.abs(Number(norm[k] ?? 0) - expected[k]) > NORM_TOLERANCE)
      if (drift) {
        issues.push({
          path: wp,
          code: 'invariant:rectNorm-consistent',
          message: 'rectNorm 与 rectPx/显示器 work 区不一致',
        })
      }
    }
    if (isInt(w.hwnd)) {
      if (seenHwnd.has(w.hwnd)) {
        issues.push({ path: wp, code: 'invariant:hwnd-unique', message: `hwnd 重复：${w.hwnd}` })
      }
      seenHwnd.add(w.hwnd)
    }
  })

  const fg = doc.desktop?.foregroundHwnd
  if (fg !== null && fg !== undefined && !seenHwnd.has(fg)) {
    issues.push({
      path: '$',
      code: 'invariant:foreground-present',
      message: 'foregroundHwnd 必须出现在 windows 列表里（被过滤掉时应写 null）',
    })
  }

  const ws = doc.workspace
  if (ws) {
    if (!byIndex.has(ws.monitor)) {
      issues.push({ path: '$', code: 'invariant:workspace-monitor', message: 'workspace.monitor 不存在' })
    }
    ;(ws.managed ?? []).forEach((mgd, j) => {
      if (isPlainObject(mgd) && mgd.hwnd !== null && mgd.hwnd !== undefined) {
        if (!seenHwnd.has(mgd.hwnd as number)) {
          issues.push({
            path: `$.workspace.managed[${j}]`,
            code: 'invariant:managed-subset',
            message: 'managed 里的 hwnd 必须在 windows 列表内',
          })
        }
      }
    })
  }
}

/**
 * 校验一份 WorkspaceSnapshot v1。
 *
 * 口径与 `docs/contracts/workspace-snapshot.v1.schema.json` +
 * `tools/verify_contracts.py` 一致：结构 → v2 越界字段 → 明文密钥 → 跨字段不变量。
 * **失败不静默**：返回全部问题（不是"第一个就返回"），便于一次看全。
 */
export function validate(input: unknown): SnapshotValidation {
  const issues: SnapshotIssue[] = []

  if (!isPlainObject(input)) {
    return {
      ok: false,
      issues: [{ path: '$', code: 'type:object', message: '快照必须是对象' }],
    }
  }

  scanTree(input, '$', issues)

  const doc = input as unknown as WorkspaceSnapshotV1

  if (doc.schemaVersion !== SNAPSHOT_SCHEMA_VERSION) {
    issues.push({
      path: '$.schemaVersion',
      code: `const:${SNAPSHOT_SCHEMA_VERSION}`,
      message: `schemaVersion 必须是 ${SNAPSHOT_SCHEMA_VERSION}`,
    })
  }
  if (typeof doc.snapshotId !== 'string' || !SNAPSHOT_ID_RE.test(doc.snapshotId)) {
    issues.push({
      path: '$.snapshotId',
      code: 'pattern:ws-YYYYMMDD-HHMMSS-xxxx',
      message: 'snapshotId 形态不合契约（ws-YYYYMMDD-HHMMSS-xxxx）',
    })
  }
  if (!isInt(doc.takenAt) || doc.takenAt < 1) {
    issues.push({ path: '$.takenAt', code: 'minimum:1', message: 'takenAt 必须是 ≥ 1 的整数' })
  }
  if (!SNAPSHOT_TRIGGERS.includes(doc.trigger)) {
    issues.push({
      path: '$.trigger',
      code: `enum:${SNAPSHOT_TRIGGERS.join(',')}`,
      message: 'v1 只有 enter_mode 会写持久快照',
    })
  }

  // source
  if (!isPlainObject(doc.source)) {
    issues.push({ path: '$.source', code: 'required:source', message: '缺少 source' })
  } else {
    const s = doc.source
    if (typeof s.appVersion !== 'string' || !s.appVersion) {
      issues.push({ path: '$.source.appVersion', code: 'minLength:1', message: 'appVersion 不能为空' })
    }
    if (!isInt(s.corePid) || s.corePid < 1) {
      issues.push({ path: '$.source.corePid', code: 'minimum:1', message: 'corePid 必须 ≥ 1' })
    }
    if (typeof s.runId !== 'string' || !s.runId) {
      issues.push({ path: '$.source.runId', code: 'minLength:1', message: 'runId 不能为空' })
    }
  }

  checkMonitors(doc.monitors, issues)

  if (!isPlainObject(doc.desktop)) {
    issues.push({ path: '$.desktop', code: 'required:desktop', message: '缺少 desktop' })
  } else {
    const d = doc.desktop
    const fg = d.foregroundHwnd
    if (fg !== null && !isInt(fg)) {
      issues.push({
        path: '$.desktop.foregroundHwnd',
        code: 'type:integer|null',
        message: 'foregroundHwnd 必须是整数或 null',
      })
    }
    if (!Array.isArray(d.windows)) {
      issues.push({ path: '$.desktop.windows', code: 'type:array', message: 'windows 必须是数组' })
    } else {
      if (d.windows.length > 200) {
        issues.push({ path: '$.desktop.windows', code: 'maxItems:200', message: 'windows 最多 200 项' })
      }
      d.windows.forEach((w, i) => checkWindowEntry(w, i, issues))
    }
  }

  if (!isPlainObject(doc.workspace)) {
    issues.push({ path: '$.workspace', code: 'required:workspace', message: '缺少 workspace' })
  } else {
    const ws = doc.workspace
    const checks: Array<[keyof SnapshotWorkspaceContext, string]> = [
      ['modeName', 'string'],
      ['modeId', 'integer'],
      ['monitor', 'integer'],
      ['launchedAppIds', 'array'],
      ['managed', 'array'],
    ]
    for (const [k, kind] of checks) {
      const v = ws[k]
      if (k === 'modeName') {
        if (typeof v !== 'string' || !v) {
          issues.push({ path: `$.workspace.${k}`, code: 'minLength:1', message: 'modeName 不能为空' })
        }
      } else if (k === 'launchedAppIds' || k === 'managed') {
        if (!Array.isArray(v)) {
          issues.push({ path: `$.workspace.${k}`, code: `type:${kind}`, message: `${k} 必须是数组` })
        }
      } else if (!isInt(v) || (v as number) < (k === 'modeId' ? 1 : 0)) {
        issues.push({
          path: `$.workspace.${k}`,
          code: `minimum:${k === 'modeId' ? 1 : 0}`,
          message: `${k} 数值不合契约`,
        })
      }
    }
    if (ws.layoutName !== null && typeof ws.layoutName !== 'string') {
      issues.push({
        path: '$.workspace.layoutName',
        code: 'type:string|null',
        message: 'layoutName 必须是字符串或 null',
      })
    }
  }

  checkInvariants(doc, issues)
  return { ok: issues.length === 0, issues }
}

// ---------------------------------------------------------------- capture()

/**
 * 窗口探针 —— **未来真实采集的注入点**。
 *
 * 本轮不实现任何 Win32 调用（窗口枚举在 core/Rust 侧，ADR-001）。
 * 真实采集接入时，只要提供一个实现了本接口的探针，`capture()` 一行都不用改。
 */
export interface WindowProbe {
  /** `false` = 探针未接线（此时 `capture()` 拒绝编造数据）。 */
  readonly wired: boolean
  source(): Promise<SnapshotSource>
  monitors(): Promise<SnapshotMonitor[]>
  windows(): Promise<SnapshotWindowEntry[]>
  foregroundHwnd(): Promise<number | null>
  workspace(): Promise<SnapshotWorkspaceContext>
}

export interface CaptureOptions {
  probe?: WindowProbe
  now?: number
  /** 用于生成 snapshotId 的随机后缀（默认取 takenAt 的 hex 片段）。 */
  idSuffix?: string
}

export interface CaptureOutcome {
  ok: boolean
  /** `true` = 本轮没有任何真实窗口探针参与（接口准备阶段的常态）。 */
  dryRun: boolean
  snapshot: WorkspaceSnapshotV1 | null
  issues: SnapshotIssue[]
  /** 降级原因（如 `probe-not-wired`）。 */
  degraded: string[]
}

/**
 * 采集一份 v1 快照。
 *
 * **没有探针就不产出快照** —— 宁可明确报"未接线"，也不编一份看起来像样的假数据
 *（那会让下游误以为恢复链已经通了）。
 *
 * 采集到的 `rectNorm` 会被**按 `deriveNormRect` 重算一遍**再写回，
 * 保证 `invariant:rectNorm-consistent` 在源头上就成立（不靠调用方自觉）。
 */
export async function capture(opts: CaptureOptions = {}): Promise<CaptureOutcome> {
  const probe = opts.probe
  if (!probe || !probe.wired) {
    const code = 'probe_not_wired'
    return {
      ok: false,
      dryRun: true,
      snapshot: null,
      degraded: ['probe-not-wired'],
      issues: [
        {
          path: '$',
          code,
          message:
            '窗口探针未接线：真实采集在 core（Rust）侧，本阶段只定接口 —— 不产出占位快照。',
        },
      ],
    }
  }

  const takenAt = opts.now ?? Date.now()
  const [source, monitors, windows, foregroundHwnd, workspace] = await Promise.all([
    probe.source(),
    probe.monitors(),
    probe.windows(),
    probe.foregroundHwnd(),
    probe.workspace(),
  ])

  const byIndex = new Map(monitors.map((m) => [m.index, m]))
  const normalized = windows.map((w) => {
    const m = byIndex.get(w.monitorIndex)
    return m ? { ...w, rectNorm: deriveNormRect(w.rectPx, m.work) } : w
  })

  const snapshot: WorkspaceSnapshotV1 = {
    schemaVersion: SNAPSHOT_SCHEMA_VERSION,
    snapshotId: makeSnapshotId(takenAt, opts.idSuffix ?? source.runId ?? ''),
    takenAt,
    trigger: 'enter_mode',
    source,
    monitors,
    desktop: { foregroundHwnd, windows: normalized },
    workspace,
  }

  const v = validate(snapshot)
  return { ok: v.ok, dryRun: false, snapshot: v.ok ? snapshot : null, issues: v.issues, degraded: [] }
}

/** 一个"未接线"的探针 —— 显式表达"现在还没有真实采集"。 */
export const nullProbe: WindowProbe = {
  wired: false,
  source: () => Promise.reject(new Error('probe-not-wired')),
  monitors: () => Promise.reject(new Error('probe-not-wired')),
  windows: () => Promise.reject(new Error('probe-not-wired')),
  foregroundHwnd: () => Promise.reject(new Error('probe-not-wired')),
  workspace: () => Promise.reject(new Error('probe-not-wired')),
}

// ---------------------------------------------------------------- restore()

export interface RestoreOptions {
  /** 当前 core 运行期标识。与快照里的 `source.runId` 不同 ⇒ 全部 hwnd 视为失效。 */
  currentRunId?: string
}

export type RestoreStepKind = 'place-window' | 'focus-window' | 'skip'

export interface RestoreStep {
  kind: RestoreStepKind
  hwnd?: number
  pid?: number
  appId?: number | null
  exeName?: string
  rect?: PxRect
  zIndex?: number
  reason: string
  /** **本轮恒为 `false`** —— 接口准备阶段不执行任何窗口/进程操作。 */
  executable: false
}

export interface RestorePlan {
  ok: boolean
  /** 恒为 `false`：本函数只产出计划，不落地执行。 */
  executable: false
  snapshotId: string | null
  mode: 'same-run' | 'stale-hwnd'
  runIdMatch: boolean
  /** 按 Z 序（升序）重放：先摆后面的，再摆前面的。 */
  steps: RestoreStep[]
  skipped: number
  /** 计划里含"需要用户确认"的动作（如重启软件）时必须为 `true`（红线 V5）。 */
  requiresUserConfirm: boolean
  issues: SnapshotIssue[]
  /**
   * 护栏声明 —— 让"不杀进程 / 不启动软件 / 不改数据库 / 不碰未登记窗口"四件事
   * 变成**可断言的数据**，而不是只写在文档里的承诺。
   */
  guardrails: {
    killsProcesses: false
    launchesApps: false
    writesDatabase: false
    touchesUnmanagedWindows: false
  }
}

const GUARDRAILS: RestorePlan['guardrails'] = {
  killsProcesses: false,
  launchesApps: false,
  writesDatabase: false,
  touchesUnmanagedWindows: false,
}

/**
 * 计算恢复计划（**只算不做**）。
 *
 * 契约语义：
 * - `runId` 不匹配 ⇒ hwnd 全部失效 ⇒ 每一步降级为 `skip`（mode=`stale-hwnd`）；
 * - `runId` 匹配 ⇒ 按 `zIndex` 升序产出 `place-window`，并对 `foregroundHwnd` 产一条 `focus-window`；
 * - 只处理 `workspace.managed` 里的窗口（**不碰未登记的窗口**）；
 * - 任何"需要把软件重新拉起来"的情形一律**不执行**，只登记 + 要求用户确认。
 */
export function restore(input: unknown, opts: RestoreOptions = {}): RestorePlan {
  const v = validate(input)
  if (!v.ok) {
    return {
      ok: false,
      executable: false,
      snapshotId: null,
      mode: 'stale-hwnd',
      runIdMatch: false,
      steps: [],
      skipped: 0,
      requiresUserConfirm: false,
      issues: v.issues,
      guardrails: GUARDRAILS,
    }
  }

  const snap = input as WorkspaceSnapshotV1
  const runIdMatch = opts.currentRunId === undefined || opts.currentRunId === snap.source.runId
  const byHwnd = new Map(snap.desktop.windows.map((w) => [w.hwnd, w]))
  const managed = snap.workspace.managed
  const steps: RestoreStep[] = []
  const issues: SnapshotIssue[] = []
  let skipped = 0
  let requiresUserConfirm = false

  if (!runIdMatch) {
    for (const m of managed) {
      steps.push({
        kind: 'skip',
        hwnd: m.hwnd ?? undefined,
        pid: m.pid ?? undefined,
        appId: m.appId,
        reason: `runId 不匹配（快照 ${snap.source.runId} ≠ 当前 ${opts.currentRunId}）：hwnd 跨运行期无效，不按旧句柄恢复`,
        executable: false,
      })
      skipped += 1
    }
    return {
      ok: true,
      executable: false,
      snapshotId: snap.snapshotId,
      mode: 'stale-hwnd',
      runIdMatch: false,
      steps,
      skipped,
      requiresUserConfirm,
      issues,
      guardrails: GUARDRAILS,
    }
  }

  const ordered = [...managed].sort((a, b) => {
    const za = a.hwnd !== null ? (byHwnd.get(a.hwnd)?.zIndex ?? 0) : 0
    const zb = b.hwnd !== null ? (byHwnd.get(b.hwnd)?.zIndex ?? 0) : 0
    return za - zb
  })

  for (const m of ordered) {
    if (m.hwnd === null) {
      // 没有句柄 ⇒ 要么它已经关了，要么需要一个"重新拉起"的动作 —— 两者都不在本轮执行范围
      requiresUserConfirm = true
      steps.push({
        kind: 'skip',
        appId: m.appId,
        pid: m.pid ?? undefined,
        reason: `「${m.appName}」无有效 hwnd：接口准备阶段不启动软件，需用户确认后才可重新拉起`,
        executable: false,
      })
      skipped += 1
      continue
    }
    const w = byHwnd.get(m.hwnd)
    if (!w) {
      issues.push({
        path: '$',
        code: 'invariant:managed-subset',
        message: `managed 里的 hwnd ${m.hwnd} 不在 windows 列表内`,
      })
      skipped += 1
      continue
    }
    steps.push({
      kind: 'place-window',
      hwnd: w.hwnd,
      pid: w.pid,
      appId: m.appId,
      exeName: w.exeName,
      rect: { ...w.rectPx },
      zIndex: w.zIndex,
      reason: `按 zIndex=${w.zIndex} 摆放到 (${w.rectPx.x},${w.rectPx.y}) ${w.rectPx.w}×${w.rectPx.h}`,
      executable: false,
    })
  }

  const fg = snap.desktop.foregroundHwnd
  if (fg !== null && byHwnd.has(fg)) {
    steps.push({
      kind: 'focus-window',
      hwnd: fg,
      pid: byHwnd.get(fg)?.pid,
      zIndex: byHwnd.get(fg)?.zIndex,
      reason: '快照时的前台窗口',
      executable: false,
    })
  }

  return {
    ok: true,
    executable: false,
    snapshotId: snap.snapshotId,
    mode: 'same-run',
    runIdMatch: true,
    steps,
    skipped,
    requiresUserConfirm,
    issues,
    guardrails: GUARDRAILS,
  }
}

/** 对外统一出口（`workspaceRuntime.snapshot.*` 用它）。 */
export const workspaceSnapshot = { capture, restore, validate }
