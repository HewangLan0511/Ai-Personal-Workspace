/**
 * TECH-01 · View Transition Progressive Enhancement（§十七）。
 *
 * 业务代码禁止直接调用 document.startViewTransition —— 统一走
 * motionViewTransition()：只有当
 *   Motion enabled + VT supported + Pack allows + 非 reduced/off + 未带 ?motion=novt
 * 全部满足时才走 VT，否则 fallback 到普通更新。
 *
 * 核心原则：VT 是增强，不是基础依赖；VT 可以 mask S2，但不能 fix S2
 * （§二十）—— 局部更新不整页 remount 的纪律不因 VT 存在而放松。
 */

import { getMotionLevel, getPerformanceLevel } from './guards'

/** Skin Pack 预留（§十八）：未来 Skin 可禁用 VT 通道。 */
let packAllowsVt = true

let urlBlocksVt = false

/** 应用启动时调用一次。 */
export function initVtFlag(): void {
  urlBlocksVt = new URLSearchParams(window.location.search).get('motion') === 'novt'
}

export function setVtPackAllows(allows: boolean): void {
  packAllowsVt = allows
}

/** VT 通道当前是否启用（测试/调试可见）。 */
export function vtEnabled(): boolean {
  if (urlBlocksVt) return false
  if (getMotionLevel() !== 'standard') return false
  if (getPerformanceLevel() === 'emergency') return false
  if (!packAllowsVt) return false
  return typeof (document as Document & { startViewTransition?: unknown }).startViewTransition === 'function'
}

/**
 * 视图更新入口：VT 可用时包一层 View Transition，否则直接执行更新。
 * 返回值与 update 的完成语义一致（VT 场景等待 finished）。
 */
export function motionViewTransition(update: () => void | Promise<void>): void | Promise<void> {
  if (!vtEnabled()) return update()
  const doc = document as Document & {
    startViewTransition: (cb: () => void | Promise<void>) => { finished: Promise<void> }
  }
  return doc.startViewTransition(update).finished
}

/** 测试/调试用：最近一次判断是否因 URL 参数回退。 */
export function isVtBlockedByParam(): boolean {
  return urlBlocksVt
}
