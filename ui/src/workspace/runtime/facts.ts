/**
 * Workspace Runtime Adapter —— facts（只读事实，TECH-07-C Phase C1/C2）
 *
 * 全部经既有 service（modeService / layoutService / appsService）走已验收命令，
 * **本文件不 import client.ts、不出现新命令**。失败如实上抛，调用方决定降级展示。
 *
 * ## C2 变更（Observe 接线）
 * - `windows` 从 core 原始 `WindowInfo` 透传改为 **`RunWindowFacts` 投影**
 *   （projection.ts 映射，core 结构不出 adapter）；
 * - `mode` 从 `ModeCurrent` 透传改为 **`RunModeFacts` 聚合投影**（当前模式 +
 *   逐软件 runState，证据链：slots pid × windows pid）；
 * - 新增拉取 `apps_list`（软件库名称表，launchedAppIds → name 映射用）——
 *   既有已验收读命令，boundary 白名单同步追加；
 * - 连接态三档：connected / degraded（部分失败）/ offline（全失败）——
 *   UI 据此展示"未连接"状态而不是伪造数据。
 */

import { layoutApi, type Layout, type MonitorInfo, type WindowInfo } from '@/api/layoutService'
import { appsApi, type AppItem } from '@/api/appsService'
import { modeApi, type ModeCurrent, type ProgressInfo, type WorkMode } from '@/api/modeService'
import {
  mapApps,
  mapWindow,
  resolveModePids,
  type RunAppFacts,
  type RunWindowFacts,
} from './projection'

// ---------------------------------------------------------------- 投影类型再导出
// RunView 只应 import 本文件的 WorkspaceFacts 与投影类型，不触碰 @/api。

export type { RunAppFacts, RunAppRunState, RunWindowFacts, RunWindowState } from './projection'

/** 当前模式的聚合事实（modes_current + modes_list + mode_progress + windows 的交集投影）。 */
export interface RunModeFacts {
  /** 当前（最近使用的）模式名；null = 未在任何模式中。 */
  running: string | null
  description: string | null
  icon: string | null
  /** 模式绑定的布局名；null = 未绑定。 */
  layout: string | null
  /** 模式拉起的软件投影（含运行状态）。 */
  apps: RunAppFacts[]
  /** 上一个模式名（exclusive 切换叙事用；core 可不提供）。 */
  previous: string | null
}

/**
 * 一次 facts 快照。`at` 是采样时刻（浏览器降级层轮询展示"数据时刻"用，
 * TECH-07-B-0 §七-3 的开放问题）。
 */
export interface WorkspaceFacts {
  at: number
  /** 当前模式聚合投影（running=null 时 apps 为空数组）。 */
  mode: RunModeFacts
  /** 正在进行中的模式应用流水线（无则 active=false）。 */
  progress: ProgressInfo | null
  /** 系统真实可管理窗口（投影）。 */
  windows: RunWindowFacts[]
  /** 布局库（数据库真相的导出视图）。 */
  layouts: Layout[]
  /** 显示器表（minimap 换算基准）。 */
  monitors: MonitorInfo[]
  /** 模式库（模板定义，取 icon/描述/绑定布局用）。 */
  modes: WorkMode[]
  /** 本次采样的失败明细（空数组 = 全部成功）。 */
  failures: string[]
  /** 连接状态：全部成功 = connected；部分失败 = degraded；全失败 = offline。 */
  connectivity: 'connected' | 'degraded' | 'offline'
}

// ---------------------------------------------------------------- 单项事实

/**
 * 系统真实可管理顶层窗口（只读；走 windows_list，C1/C2 不提供任何摆窗路径）。
 * `pids`：当前模式流水线已登记的 pid 集合（归属判据）；缺省空集合 → 全部窗口
 * belongsToMode=false（没有证据就不判归属，禁止按标题猜）。
 */
export async function windows(pids: ReadonlySet<number> = new Set()): Promise<RunWindowFacts[]> {
  const list = await layoutApi.windowsList()
  return list.map((w) => mapWindow(w, pids))
}

/** 布局库。 */
export async function layouts(): Promise<Layout[]> {
  return layoutApi.list()
}

/** 显示器表。 */
export async function monitors(): Promise<MonitorInfo[]> {
  return layoutApi.monitors()
}

/** 模式库（工作模式模板定义）。 */
export async function modes(): Promise<WorkMode[]> {
  return modeApi.list()
}

/** 软件库（launchedAppIds → name 映射用；既有 apps_list 读命令）。 */
export async function apps(): Promise<AppItem[]> {
  return appsApi.list()
}

/** 正在进行的模式应用进度（无进行中流程时 active=false）。 */
export async function modeProgress(): Promise<ProgressInfo> {
  return modeApi.progress()
}

/** core 运行注册表（apps_running：appId → pid；失败返回 {}，不算连接失败）。 */
export async function runningApps(): Promise<Record<string, number>> {
  return appsApi.running()
}

// ---------------------------------------------------------------- 聚合快照

/** 快照聚合的拉取项数（connectivity 的 offline 判据用）。 */
const CORE_FETCH_COUNT = 6 // core 连接证据 = 6 项 core 事实；apps_list 有 localStorage 降级，不算

/** 最近一次快照缓存（归属校验数据源；C3 placeWindow 用，null = 从未成功拉取）。 */
let lastFacts: WorkspaceFacts | null = null

/** 最近一次 facts 快照（只读视图；placeWindow 的归属校验以此为准）。 */
export function lastSnapshot(): WorkspaceFacts | null {
  return lastFacts
}

/**
 * 聚合一次快照。单项失败不拖垮整份快照（降级为 null / 空数组并记入 failures）——
 * 与 core 七步流水线"单点失败不中断"同一口径。**每项只拉一次，无重复调用。**
 */
export async function snapshot(): Promise<WorkspaceFacts> {
  const failures: string[] = []
  const [currentR, progressR, rawWinsR, layoutsR, monitorsR, modesR, appsR] =
    await Promise.allSettled([
      modeApi.current() as Promise<ModeCurrent>,
      modeProgress(),
      layoutApi.windowsList() as Promise<WindowInfo[]>,
      layouts(),
      monitors(),
      modes(),
      apps(),
    ])
  if (currentR.status === 'rejected') failures.push(`modes_current: ${currentR.reason}`)
  if (progressR.status === 'rejected') failures.push(`mode_progress: ${progressR.reason}`)
  if (rawWinsR.status === 'rejected') failures.push(`windows_list: ${rawWinsR.reason}`)
  if (layoutsR.status === 'rejected') failures.push(`layouts_list: ${layoutsR.reason}`)
  if (monitorsR.status === 'rejected') failures.push(`monitors_list: ${monitorsR.reason}`)
  if (modesR.status === 'rejected') failures.push(`modes_list: ${modesR.reason}`)
  if (appsR.status === 'rejected') failures.push(`apps_list: ${appsR.reason}`)

  // 运行注册表：失败静默降级 {}（appsApi.running 自带 try/catch），不进 failures
  const runningMap = await runningApps()

  const current = currentR.status === 'fulfilled' ? currentR.value : null
  const progressOk = progressR.status === 'fulfilled' ? progressR.value : null
  const modesOk = modesR.status === 'fulfilled' ? modesR.value : []
  const appsOk = appsR.status === 'fulfilled' ? appsR.value : []

  // 窗口投影：归属判据 = 流水线 slots pid ∪ 运行注册表中当前模式 app 的 pid
  const pids = resolveModePids(progressOk, current, runningMap)
  const windowsProjected: RunWindowFacts[] =
    rawWinsR.status === 'fulfilled' ? rawWinsR.value.map((w) => mapWindow(w, pids)) : []

  const meta =
    current?.running != null ? (modesOk.find((m) => m.name === current.running) ?? null) : null
  const modeProjected: RunModeFacts = {
    running: current?.running ?? null,
    description: meta?.description ?? null,
    icon: meta?.icon ?? null,
    layout: meta?.layout ?? null,
    apps: mapApps(current, progressOk, appsOk, windowsProjected),
    previous: current?.previous ?? null,
  }

  // 连接态判据：只看 core 事实的失败数。apps_list 在浏览器下降级 localStorage
  // （appsService 设计行为，fulfilled 不进 failures），不能算"core 已连上"的证据。
  const coreFailures = failures.length - (appsR.status === 'rejected' ? 1 : 0)
  const connectivity =
    coreFailures === 0 ? 'connected' : coreFailures >= CORE_FETCH_COUNT ? 'offline' : 'degraded'

  const facts: WorkspaceFacts = {
    at: Date.now(),
    mode: modeProjected,
    progress: progressOk,
    windows: windowsProjected,
    layouts: layoutsR.status === 'fulfilled' ? layoutsR.value : [],
    monitors: monitorsR.status === 'fulfilled' ? monitorsR.value : [],
    modes: modesOk,
    failures,
    connectivity,
  }
  // 归属校验的数据源：只缓存"至少 windows 拉到了"的快照（避免旧 hwnd 残留误判）。
  // C3 closure audit：core 不可达（offline）时**必须作废缓存** —— 否则 core 重启后
  // 陈旧快照会把旧 hwnd 当成"当前事实"，actuation 可能作用到不再归属的窗口上。
  // 缓存是纯运行时上下文，绝不落盘；恢复连接后下一次采样自然重建。
  if (connectivity === 'offline') lastFacts = null
  else if (rawWinsR.status === 'fulfilled') lastFacts = facts
  return facts
}

/** 快照采样失败的明细（空数组 = 全部成功）。供 UI 如实展示降级原因。 */
export function failuresOf(f: WorkspaceFacts): string[] {
  return f.failures
}
