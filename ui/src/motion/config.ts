/**
 * TECH-01 · Motion 常量与优先级表（§七/§十一/§十四）。
 *
 * Duration 与 Intensity 解耦（§七）：本表只管时长；
 * 幅度一律由 `--mt-intensity` 等 CSS 变量在消费端控制。
 */

/** Conflict Guard 优先级（§十一）：数值越小优先级越高，只有队首是 Primary。 */
export const MOTION_PRIORITY = [
  'system', // System / Critical
  'cinema', // Workspace Cinema
  'drag', // Drag
  'overlay', // Modal / Drawer
  'page', // Page Transition
  'local', // Local Change
  'hover', // Hover
  'idle', // Idle
] as const

export type MotionPriority = (typeof MOTION_PRIORITY)[number]

export function priorityRank(p: MotionPriority): number {
  return MOTION_PRIORITY.indexOf(p)
}

/** Duration Token（§七）。数值 = motion-tokens.css 中对应变量，双处同步。 */
export const DUR = {
  instant: 0,
  quick: 120,
  base: 180,
  panel: 240,
  scene: 320,
  cinematic: 560,
} as const

export type DurationToken = keyof typeof DUR

/** Page Transition（§十五）：content-only，160–220ms 默认取 out 160 / in 200。 */
export const PAGE_TRANSITION = { outMs: 160, inMs: 200 } as const

/** Workspace Cinema 时间轴（§十四，ms）。 */
export const CINEMA = {
  begin: 80,
  switch: 160,
  positioning: 240, // == Interactive Gate
  gate: 240,
  stable: 560,
} as const

/** Interrupt Guard：非瞬时动画的最大生命周期 = duration + FORCE_FINISH_EXTRA。 */
export const FORCE_FINISH_EXTRA = 1000
