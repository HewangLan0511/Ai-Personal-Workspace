/**
 * Workspace Runtime Adapter —— 投影层（TECH-07-C Phase C2 · Observe 接线）
 *
 * ## 职责（UI-FUSION-STANDARD §四 + C2 指令 §三）
 * 把 core 原始返回结构（layoutService/modeService 的 DTO）映射成 RunView 消费的
 * **投影事实**——RunView 只认识本文件的类型，不知道 WindowInfo/SlotResult 等
 * core 形状，更不知道 command 名。
 *
 * ## 映射原则
 * - **只映射，不伪造**：core 没有的字段如实给 null/unknown（如 exe——core 的
 *   WindowInfo 不含进程映像路径，C2 不新增 core 命令，故 exe 恒为 null，
 *   属"已知数据缺口"而非"漏接线"，见 C2 报告风险表）；
 * - **归属判据唯一**：窗口"属于当前工作模式" = 该窗口 pid ∈ 当前模式流水线
 *   已登记的进程 pid 集合（mode_progress.slots 的 pid）。无 pid 证据时一律
 *   belongsToMode=false —— 禁止按标题关键词猜归属；
 * - **可管理语义**：windows_list 的返回本身就是 core「可管理顶层窗口」过滤
 *   （07 §1：可见+非工具窗+有尺寸+有标题）之后的集合，因此能出现在 facts 里的
 *   窗口 manageable 恒为 true；"不可管理窗口"根本不会进入本层（如实标注）。
 */

import type { WindowInfo } from '@/api/layoutService'
import type { ModeCurrent, ProgressInfo, SlotResult } from '@/api/modeService'
import type { AppItem } from '@/api/appsService'

// ---------------------------------------------------------------- 窗口事实

/** 窗口运行状态（core 的 minimized/maximized/visible 三位的投影）。 */
export type RunWindowState = 'normal' | 'minimized' | 'maximized'

/**
 * RunView 消费的窗口事实（不泄漏 core 的 WindowInfo 结构）。
 * exe 为 null 是**如实缺口**：core WindowInfo 无进程映像路径，C2 不新增命令。
 */
export interface RunWindowFacts {
  hwnd: number
  pid: number
  title: string
  className: string
  /** 进程映像路径。C2 恒为 null（core 未提供，禁止伪造）。 */
  exe: string | null
  state: RunWindowState
  /** 像素矩形；最小化时 core 不给（IsIconic 下 GetWindowRect 无意义）→ null。 */
  rect: { x: number; y: number; w: number; h: number } | null
  /** 是否属于当前工作模式（判据：pid ∈ 模式流水线已登记 pid 集合）。 */
  belongsToMode: boolean
  /** 可管理窗口（windows_list 返回即过滤后集合）；本层恒 true。 */
  manageable: boolean
}

/** 提取模式流水线已登记的真实进程 pid 集合（唯一归属判据的数据源）。 */
export function modePidsOf(progress: ProgressInfo | null): Set<number> {
  const pids = new Set<number>()
  for (const s of progress?.slots ?? []) {
    if (typeof s.pid === 'number' && s.pid > 0) pids.add(s.pid)
  }
  return pids
}

/**
 * C3 归属 pid 全集（两种都来自 core 的真实登记，禁止任何猜测）：
 * 1. 模式流水线 slots 的 pid（进行中/刚完成的启动证据）；
 * 2. core 运行注册表（apps_running：appId → pid，5s watcher 维护）中
 *    **属于当前模式 launchedAppIds** 的 pid —— 流水线结束、slots 清空后，
 *    只要模式仍是"当前模式"，运行注册表就是持续证据。
 */
export function resolveModePids(
  progress: ProgressInfo | null,
  current: ModeCurrent | null,
  runningMap: Record<string, number>,
): Set<number> {
  const pids = modePidsOf(progress)
  const launched = new Set(current?.launchedAppIds ?? [])
  if (launched.size > 0) {
    for (const [appId, pid] of Object.entries(runningMap)) {
      if (launched.has(Number(appId)) && Number(pid) > 0) pids.add(Number(pid))
    }
  }
  return pids
}

/** core WindowInfo → RunWindowFacts 投影（纯函数）。 */
export function mapWindow(w: WindowInfo, modePids: ReadonlySet<number>): RunWindowFacts {
  const state: RunWindowState = w.minimized ? 'minimized' : w.maximized ? 'maximized' : 'normal'
  return {
    hwnd: w.hwnd,
    pid: w.pid,
    title: w.title,
    className: w.class_name,
    exe: null, // 如实缺口：core 不提供，见文件头说明
    state,
    rect: w.rect ? { x: w.rect.x, y: w.rect.y, w: w.rect.w, h: w.rect.h } : null,
    belongsToMode: modePids.has(w.pid),
    manageable: true,
  }
}

// ---------------------------------------------------------------- 模式事实

/** 单个软件的运行状态（观察口径：进程证据来自流水线 slots，窗口证据来自 windows_list）。 */
export type RunAppRunState = 'running' | 'launching' | 'failed' | 'skipped' | 'unknown'

/** RunView appbar / 状态栏 chips 消费的软件事实。 */
export interface RunAppFacts {
  /** 软件库 id（modes_current.launchedAppIds 的元素）；无 id 证据时 null。 */
  appId: number | null
  /** 软件名（apps_list 的 name；拿不到时回退 `应用 #<id>`）。 */
  name: string
  runState: RunAppRunState
  /** 该软件名下当前可管理窗口数（按 pid 归属统计）。 */
  windowCount: number
}

/**
 * RunView 顶栏 / 状态栏消费的模式事实。
 * apps 的 runState 判据（观察口径，全部有证据链，禁止拍脑袋）：
 * - slots 有该 app 记录：launched → 窗口已匹配 pid ? running : launching；
 *   failed → failed；skipped_cancelled → skipped；
 * - 无 slots（流水线未跑/已清）：只有 launchedAppIds 证据 → unknown
 *   （core 未提供"当前运行中的软件↔pid"映射，不伪造 running）。
 */
export function mapApps(
  current: ModeCurrent | null,
  progress: ProgressInfo | null,
  apps: AppItem[],
  windows: RunWindowFacts[],
): RunAppFacts[] {
  const running = current?.running ?? null
  if (!running) return []

  const slots = progress?.slots ?? []
  const nameOf = (appId: number): string =>
    apps.find((a) => a.id === appId)?.name ?? `应用 #${appId}`
  // pid → appId（slots 是唯一同时带 app/appId/pid 的证据）
  const pidToApp = new Map<number, SlotResult>()
  for (const s of slots) if (typeof s.pid === 'number' && s.pid > 0) pidToApp.set(s.pid, s)
  const windowsByPid = new Map<number, number>()
  for (const w of windows) windowsByPid.set(w.pid, (windowsByPid.get(w.pid) ?? 0) + 1)

  const out: RunAppFacts[] = []
  const seen = new Set<number>()
  // 1) 有流水线证据的 app（slots 顺序 = 启动顺序）
  for (const s of slots) {
    if (s.appId !== null && seen.has(s.appId)) continue
    if (s.appId !== null) seen.add(s.appId)
    const pidOk = typeof s.pid === 'number' && s.pid > 0
    const winCount = pidOk ? (windowsByPid.get(s.pid as number) ?? 0) : 0
    let runState: RunAppRunState
    if (s.status === 'failed') runState = 'failed'
    else if (s.status === 'skipped_cancelled') runState = 'skipped'
    else if (!pidOk) runState = 'unknown'
    else runState = winCount > 0 ? 'running' : 'launching'
    out.push({
      appId: s.appId,
      name: s.app || (s.appId !== null ? nameOf(s.appId) : '未知软件'),
      runState,
      windowCount: winCount,
    })
  }
  // 2) 只有 launchedAppIds 证据、无 slots 的 app（流水线已清的历史状态）→ unknown
  for (const appId of current?.launchedAppIds ?? []) {
    if (seen.has(appId)) continue
    seen.add(appId)
    out.push({ appId, name: nameOf(appId), runState: 'unknown', windowCount: 0 })
  }
  return out
}
