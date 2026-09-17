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
import { initVtFlag, motionViewTransition, vtEnabled, setVtPackAllows } from './viewTransition'
import { startCinema, type CinemaHandle, type CinemaOptions } from './cinema'
import {
  applySkin, applySkinJson, clearSkin, getActiveSkinId, listSkins,
  BUILTIN_SKINS, SKIN_SCHEMA_VERSION,
  type SkinDefinition, type SkinLoadReport, type SkinOverrides,
} from './skin'
import { CINEMA, DUR, PAGE_TRANSITION, MOTION_PRIORITY, type DurationToken, type MotionPriority } from './config'

export { guards, claim, runInterruptible, createPageTransitionHooks, motionViewTransition, vtEnabled, startCinema }
export * from './skin'
export type { MotionClaim, InterruptibleAnim, AnimOptions, CinemaHandle, CinemaOptions, DurationToken, MotionPriority, SkinDefinition, SkinLoadReport, SkinOverrides }
export { CINEMA, DUR, PAGE_TRANSITION, MOTION_PRIORITY }
export { hasActiveClaims, hasPendingPageAnims }

export function initMotionRuntime(): void {
  guards.initMotionGuard()
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
  config: { CINEMA: typeof CINEMA; DUR: typeof DUR; PAGE_TRANSITION: typeof PAGE_TRANSITION; MOTION_PRIORITY: typeof MOTION_PRIORITY }
  skin: {
    apply: typeof applySkin
    applyJson: typeof applySkinJson
    clear: typeof clearSkin
    active: typeof getActiveSkinId
    list: typeof listSkins
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
    config: { CINEMA, DUR, PAGE_TRANSITION, MOTION_PRIORITY },
    skin: {
      apply: applySkin,
      applyJson: applySkinJson,
      clear: clearSkin,
      active: getActiveSkinId,
      list: listSkins,
      builtin: BUILTIN_SKINS,
      schemaVersion: SKIN_SCHEMA_VERSION,
    },
  }
}
