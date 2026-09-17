/**
 * TECH-01 · Motion Guard（§九）+ Performance Guard（§十）。
 *
 * - Motion Guard：standard / reduced / off 三档。系统 prefers-reduced-motion
 *   自动进 reduced；用户显式设置优先于系统（持久化到 localStorage）。
 * - Performance Guard：normal / reduced / emergency 三档，只降表现
 *   （blur/shadow/同时动画/intensity），不碰布局逻辑（§十硬规则）。
 *
 * 两者的档位通过 documentElement 的 data-motion / data-perf 属性下发给
 * CSS（motion-tokens.css 中的变量映射），JS 侧提供数值供动画计算。
 */

export type MotionLevel = 'standard' | 'reduced' | 'off'
export type PerfLevel = 'normal' | 'reduced' | 'emergency'

const LS_KEY = 'pw.motion.level'

let motionLevel: MotionLevel = 'standard'
let userOverride: MotionLevel | null = null
let perfLevel: PerfLevel = 'normal'
let media: MediaQueryList | null = null
const listeners = new Set<() => void>()

function apply(): void {
  const root = document.documentElement
  root.dataset.motion = motionLevel
  root.dataset.perf = perfLevel
}

function systemLevel(): MotionLevel {
  return media?.matches ? 'reduced' : 'standard'
}

function setMotionLevelInternal(level: MotionLevel): void {
  if (motionLevel === level) return
  motionLevel = level
  apply()
  for (const fn of listeners) fn()
}

/** 应用启动时调用一次。 */
export function initMotionGuard(): void {
  media = window.matchMedia('(prefers-reduced-motion: reduce)')
  const saved = localStorage.getItem(LS_KEY)
  userOverride =
    saved === 'standard' || saved === 'reduced' || saved === 'off' ? saved : null
  motionLevel = userOverride ?? systemLevel()
  media.addEventListener('change', () => {
    if (userOverride === null) setMotionLevelInternal(systemLevel())
  })
  apply()
}

/** 用户显式设置（优先于系统偏好）；传 null 清除覆盖、回到系统偏好。 */
export function setMotionLevel(level: MotionLevel | null): void {
  userOverride = level
  if (level === null) {
    localStorage.removeItem(LS_KEY)
    setMotionLevelInternal(systemLevel())
  } else {
    localStorage.setItem(LS_KEY, level)
    setMotionLevelInternal(level)
  }
}

export function getMotionLevel(): MotionLevel {
  return motionLevel
}

export function getPerformanceLevel(): PerfLevel {
  return perfLevel
}

export function setPerformanceLevel(level: PerfLevel): void {
  if (perfLevel === level) return
  perfLevel = level
  apply()
  for (const fn of listeners) fn()
}

/** 装饰性动画是否允许（reduced/off 下不允许）。 */
export function decorativeAllowed(): boolean {
  return motionLevel === 'standard'
}

/** 必要状态反馈（focus/state/progress/loading 等）任何档位都保留。 */
export function essentialFeedbackAllowed(): boolean {
  return true
}

/** 当前 intensity 数值（读取已生效的 CSS 变量，与 CSS 档位永远一致）。 */
export function intensity(): number {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue('--mt-intensity')
    .trim()
  const n = Number.parseFloat(raw)
  return Number.isFinite(n) ? n : 1
}

/** 订阅档位变化（Motion Guard 或 Performance Guard 任一变化都触发）。 */
export function onGuardChange(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
