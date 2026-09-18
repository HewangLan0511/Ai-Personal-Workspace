/**
 * TECH-01 · Motion Runtime 门面（§十九）。
 *
 * 组件不自带动画系统：Button/Card/Workspace 都经由本运行时取 motion 能力。
 * 本模块同时是 Skin 接口的落点（§十八，skin-system.md v1.0 已实现）：
 *   Core Motion（本运行时，安全规则不可变）
 *     → Motion Guard（不可被 Skin 关闭；off/reduced 硬设最终变量，高于 Skin）
 *     → Skin Motion Profile（skin.ts：--mt-skin-* 通道 + --accent 白名单覆盖）
 *     → Component Motion
 *
 * Skin 可以改：intensity、drift、scale-on、blur、duration（5 档白名单）、
 * easing（3 档白名单）、stagger、accent。
 * Skin 永远不能改：Interactive Gate、Motion Guard、Reduced/Off、
 * Conflict Priority、Interrupt Rule、State Safety、Drag/Workspace/Page 逻辑
 * —— 这些不经过 Skin 通道，直接常量/闭包固化在本运行时内。
 */

import * as guards from './guards'
import { claim, hasActiveClaims, type MotionClaim } from './conflict'
import { runInterruptible, type AnimOptions, type InterruptibleAnim } from './interrupt'
import { createPageTransitionHooks, hasPendingPageAnims } from './pageTransition'
import { playEntrance, usePageEntrance, resetEntranceHistory } from './entrance'
import { initVtFlag, motionViewTransition, vtEnabled, setVtPackAllows } from './viewTransition'
import { startCinema, type CinemaHandle, type CinemaOptions } from './cinema'
import {
  applySkin, applySkinJson, clearSkin, getActiveSkinId, listSkins, restoreSkin,
  BUILTIN_SKINS, SKIN_SCHEMA_VERSION,
  type SkinDefinition, type SkinLoadReport, type SkinOverrides,
} from './skin'
import { CINEMA, DUR, PAGE_TRANSITION, MOTION_PRIORITY, type DurationToken, type MotionPriority } from './config'

export { guards, claim, runInterruptible, createPageTransitionHooks, motionViewTransition, vtEnabled, startCinema }
export { playEntrance, usePageEntrance, resetEntranceHistory }
export type { UsePageEntranceOptions } from './entrance'
/**
 * Motion Guard 的**具名导出**（设置页 · 外观的「动画」三档要直接调，不该绕
 * `guards.setMotionLevel` 这种间接写法 —— 同一件事在组件里只留一种拼写）。
 * 只导出"产品用得上的那几个"：档位读写、档位订阅、当前幅度。
 */
export {
  getMotionLevel,
  setMotionLevel,
  getPerformanceLevel,
  setPerformanceLevel,
  onGuardChange,
  intensity,
  decorativeAllowed,
} from './guards'
export type { MotionLevel, PerfLevel } from './guards'
export * from './skin'
export type { MotionClaim, InterruptibleAnim, AnimOptions, CinemaHandle, CinemaOptions, DurationToken, MotionPriority, SkinDefinition, SkinLoadReport, SkinOverrides }
export { CINEMA, DUR, PAGE_TRANSITION, MOTION_PRIORITY }
export { hasActiveClaims, hasPendingPageAnims }

/**
 * 读取 motion token 的毫秒值 —— 给"等动画播完再换 DOM"这类 **JS 编排点**用。
 *
 * 为什么需要：CSS 动画的时长必须走 token（Skin/Guard 才能改档），但 JS 侧要
 * `setTimeout` 等一个窗口时，如果自己写死毫秒值，就会出现"动画已经被 Guard 归零、
 * JS 还在等 240ms"的错位（表现为换页有一拍空等，off 档尤其明显）。
 * 本函数把 token 的**当前计算值**读出来，JS 与 CSS 因此永远是同一个数。
 *
 * 对应原型 `mtMs(name, fallback)`（index.html 脚本段）。原型读 `--mt-dur-*`，
 * 本工程同样只读 `--mt-*`，不新增时长事实来源。
 *
 * @param name CSS 自定义属性名，如 `--mt-dur-dwell`
 * @param fallback 读不到时（SSR / 未挂载 / token 未定义）的兜底毫秒值
 */
export function motionMs(name: string, fallback = 0): number {
  if (typeof document === 'undefined') return fallback
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  if (!raw) return fallback
  const n = Number.parseFloat(raw)
  if (Number.isNaN(n)) return fallback
  return raw.endsWith('ms') ? n : raw.endsWith('s') ? n * 1000 : n
}


export function initMotionRuntime(): void {
  guards.initMotionGuard()
  // skin-system.md §9.2 第 6 项：启动恢复上次选的皮肤。
  // 顺序有意放在 Motion Guard **之后**：降级层必须最后落定，皮肤只是给
  // `--mt-skin-*` 通道赋值，Guard 的最终值在 CSS 里天然高于它（§8.3 正交开关）。
  restoreSkin()
  initVtFlag()
  exposeDebug()
}

/** 测试/调试/未来设置页的受控入口。命名带 Debug 以示非产品 API。 */
export interface MotionDebug {
  setLevel: typeof guards.setMotionLevel
  getLevel: typeof guards.getMotionLevel
  setPerformance: typeof guards.setPerformanceLevel
  getPerformance: typeof guards.getPerformanceLevel
  startCinema: typeof startCinema
  claim: typeof claim
  hasActiveClaims: typeof hasActiveClaims
  runInterruptible: typeof runInterruptible
  vtEnabled: typeof vtEnabled
  motionViewTransition: typeof motionViewTransition
  setVtPackAllows: typeof setVtPackAllows
  hasPendingPageAnims: typeof hasPendingPageAnims
  /** 页面元素进出场（`[data-enter]` → `.enter-up` 错峰）；探针可主动重播。 */
  playEntrance: typeof playEntrance
  config: { CINEMA: typeof CINEMA; DUR: typeof DUR; PAGE_TRANSITION: typeof PAGE_TRANSITION; MOTION_PRIORITY: typeof MOTION_PRIORITY }
  skin: {
    apply: typeof applySkin
    applyJson: typeof applySkinJson
    clear: typeof clearSkin
    active: typeof getActiveSkinId
    list: typeof listSkins
    restore: typeof restoreSkin
    builtin: typeof BUILTIN_SKINS
    schemaVersion: typeof SKIN_SCHEMA_VERSION
  }
}

declare global {
  interface Window {
    __pwMotion?: MotionDebug
  }
}

function exposeDebug(): void {
  if (window.__pwMotion) return
  window.__pwMotion = {
    setLevel: guards.setMotionLevel,
    getLevel: guards.getMotionLevel,
    setPerformance: guards.setPerformanceLevel,
    getPerformance: guards.getPerformanceLevel,
    startCinema,
    claim,
    hasActiveClaims,
    runInterruptible,
    vtEnabled,
    motionViewTransition,
    setVtPackAllows,
    hasPendingPageAnims,
    playEntrance,
    config: { CINEMA, DUR, PAGE_TRANSITION, MOTION_PRIORITY },
    skin: {
      apply: applySkin,
      applyJson: applySkinJson,
      clear: clearSkin,
      active: getActiveSkinId,
      list: listSkins,
      restore: restoreSkin,
      builtin: BUILTIN_SKINS,
      schemaVersion: SKIN_SCHEMA_VERSION,
    },
  }
}
