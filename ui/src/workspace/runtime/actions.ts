/**
 * Workspace Runtime Adapter —— actions（经既有命令的写动作，TECH-07-C C1/C3）
 *
 * - C1：非窗口控制的三个模式动作（apply / cancel / exit）；
 * - C3：**placeWindow** —— 唯一放开的窗口控制（windows_place，移动/缩放）。
 *   归属规则冻结（C2 §五）：hwnd 必须能在最近一次 facts 快照中找到、
 *   belongsToMode 且 manageable —— 否则 unbound 拒绝，绝不误操作其他窗口。
 *   坐标语义（§8）：intent 为归一化几何（相对主显示器工作区 0..1），本层换算成
 *   Windows 虚拟屏幕物理像素（core 为 per-monitor DPI 感知，windows_place 即物理 px）。
 * - 仍禁止：windows_activate/close、恢复（mode_restore / snapshot）、apps_launch（见 boundary；
 *   C5 起布局保存/应用移入 runtime/layout.ts，不经本文件）。
 */

import { layoutApi } from '@/api/layoutService'
import { modeApi, type ApplyOutcome } from '@/api/modeService'
import { ADAPTER_MODE, type AdapterMode } from './boundary'
import { lastSnapshot } from './facts'

/** 动作被当前段位拒绝（actuate 未放开 / 命令不在白名单）。 */
export class ActionBlockedError extends Error {
  readonly command: string
  readonly mode: AdapterMode
  constructor(command: string, mode: AdapterMode, reason: string) {
    super(`动作「${command}」在 ${mode} 段被拒绝：${reason}`)
    this.name = 'ActionBlockedError'
    this.command = command
    this.mode = mode
  }
}

/**
 * 归一化几何下限（C7-B：全链唯一 MIN 来源 —— RunView 预览与 placeWindow 共用本常量，
 * 禁止任何一侧私设第二份）。取 adapter 原值 0.02：C3/C4 place contract 零变更。
 */
export const MIN_NORM = 0.02

/**
 * 监视器边缘吸附阈值（归一化，C7-D：仅作用于预览层，commit 语义不变）。
 * 与 MIN_NORM 同放本文件 —— geometry 常量单一来源。
 */
export const SNAP_NORM = 0.02

/**
 * 进入模式（mode_apply，既有命令）。
 * C3 起 actuate 段放行。
 */
export async function applyMode(modeId: number, policy?: string): Promise<ApplyOutcome> {
  if (ADAPTER_MODE !== 'actuate') {
    throw new ActionBlockedError('mode_apply', ADAPTER_MODE, 'observe 段只读')
  }
  return modeApi.apply(modeId, policy)
}

/** 取消进行中的模式应用（mode_cancel；不属窗口控制，observe 段也放行）。 */
export async function cancelApply(): Promise<{
  cancelled: boolean
  modeName?: string
  reason?: string
}> {
  return modeApi.cancel()
}

/** 退出当前模式（mode_exit）。⚠️ core 侧目前是硬杀语义（07-A R-1），C3 仍不从 Run 页暴露。 */
export async function exitMode(): Promise<{ closed: string[] }> {
  return modeApi.exit()
}

// ---------------------------------------------------------------- 窗口摆位（C3）

/** 摆位意图：归一化几何，相对主显示器**工作区**（不含任务栏）左上角。 */
export interface PlacementIntent {
  hwnd: number
  /** 0..1，相对工作区宽/高。 */
  x: number
  y: number
  w: number
  h: number
}

/** 摆位结果（§9 失败语义：绝不假装成功）。 */
export type PlacementStatus = 'placed' | 'unbound' | 'offline' | 'failed'

export interface PlacementResult {
  status: PlacementStatus
  hwnd: number
  /** placed 时：core 实际收到的物理像素矩形（Windows 虚拟屏幕坐标）。 */
  rect?: { x: number; y: number; w: number; h: number }
  message?: string
}

/** 摆位执行所需的工作区（物理像素，来自 monitors facts 的主显示器）。 */
export interface WorkArea {
  x: number
  y: number
  w: number
  h: number
}

/**
 * 移动/缩放一个**归属当前工作模式**的真实窗口（windows_place，C3 唯一窗口控制）。
 *
 * 校验顺序（全部在 adapter 内，RunView 不可见）：
 * 1. 段位 = actuate（否则 ActionBlockedError）；
 * 2. hwnd ∈ 最近 facts 快照 && belongsToMode && manageable（否则 unbound）；
 * 3. 归一化 intent → 物理像素 rect（clamp 到工作区内）→ windows_place。
 *
 * 不做：激活、关闭、重启、恢复 —— placement 失败只如实返回 failed。
 */
export async function placeWindow(
  intent: PlacementIntent,
  workArea: WorkArea,
): Promise<PlacementResult> {
  if (ADAPTER_MODE !== 'actuate') {
    throw new ActionBlockedError('windows_place', ADAPTER_MODE, '窗口控制未放开')
  }

  const snap = lastSnapshot()
  // C3 closure audit（fail-closed）：core 不可达/无快照时**不发起** windows_place ——
  // 没有真实事实就没有归属依据，宁可 offline 也不能对陈旧 hwnd 下手。
  if (!snap || snap.connectivity === 'offline') {
    return {
      status: 'offline',
      hwnd: intent.hwnd,
      message: !snap ? '尚无真实窗口事实（core 未连接）' : 'core 未连接 —— 摆位未执行',
    }
  }
  const win = snap.windows.find((w) => w.hwnd === intent.hwnd)
  if (!win || !win.belongsToMode || !win.manageable) {
    return {
      status: 'unbound',
      hwnd: intent.hwnd,
      message: !win
        ? '窗口不在当前真实窗口事实中（可能已关闭）'
        : !win.belongsToMode
          ? '窗口不属于当前工作模式（归属判据：pid ∈ 模式流水线）'
          : '窗口不可管理',
    }
  }

  const wa = workArea
  if (wa.w <= 0 || wa.h <= 0) {
    return { status: 'failed', hwnd: intent.hwnd, message: '工作区几何无效（monitors facts）' }
  }
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
  // C7-A：intent 各分量先独立 clamp（保持 C3 契约口径），再**联合校验**整窗完整落在
  // 工作区内（C5-06 闭环：旧实现 x/w 独立 clamp，x+w 可 >1 ⇒ 摆位后窗口部分出界）。
  // 该校验对 move 与全部 8 向 resize 统一生效（最终 geometry 校验只有这一处）。
  const w = clamp(intent.w, MIN_NORM, 1)
  const h = clamp(intent.h, MIN_NORM, 1)
  const nx = clamp(clamp(intent.x, 0, 1), 0, 1 - w)
  const ny = clamp(clamp(intent.y, 0, 1), 0, 1 - h)
  const wPx = Math.round(w * wa.w)
  const hPx = Math.round(h * wa.h)
  let xPx = Math.round(wa.x + nx * wa.w)
  let yPx = Math.round(wa.y + ny * wa.h)
  // 联合收口（含舍入误差）：右/下边缘绝不越过工作区
  xPx = Math.min(xPx, wa.x + wa.w - wPx)
  yPx = Math.min(yPx, wa.y + wa.h - hPx)
  const rect = { x: xPx, y: yPx, w: wPx, h: hPx }

  try {
    await layoutApi.place(win.hwnd, rect)
    return { status: 'placed', hwnd: win.hwnd, rect }
  } catch (e) {
    // §9：offline 与 failed 分开 —— 代理/连接类错误如实归为 offline
    const code = (e as { code?: string })?.code ?? ''
    const offline = code === 'proxy_down' || code === 'network' || code === 'timeout'
    return {
      status: offline ? 'offline' : 'failed',
      hwnd: intent.hwnd,
      message: String((e as Error)?.message ?? e),
    }
  }
}
