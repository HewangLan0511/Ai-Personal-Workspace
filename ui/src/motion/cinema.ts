/**
 * TECH-01 · Workspace Cinema Runtime（§十四）。
 *
 * Cinema 不是普通 Page Transition，是独立的空间原语：
 *   0–80ms    Begin
 *   80–160ms  Workspace switch
 *   120–240ms Window positioning
 *   240ms     Interactive Gate —— 到达后用户必须恢复交互，
 *             动画后半段（240–560ms）只做 Background Stabilization
 *   560ms     Stable
 *
 * 必须支持：Interrupt / Resize / Cancel / Finish / Final State Override。
 * Resize：取消空间动画 → 重新计算最终布局 → 快速收敛（§十四）。
 *
 * 本阶段只交付原语本身（产品侧工作台尚未接线，业务无感知）；
 * trace 数组记录各阶段实际发生时间，供 Test 3/4 机器断言。
 */

import { CINEMA } from './config'

export type CinemaPhase =
  | 'idle'
  | 'begin'
  | 'switch'
  | 'positioning'
  | 'gate'
  | 'stabilization'
  | 'stable'
  | 'cancelled'

export interface CinemaTraceEntry {
  phase: CinemaPhase
  /** 相对 start() 的毫秒数。 */
  t: number
}

export interface CinemaOptions {
  /** 80–160ms：执行 workspace 切换（业务挂钩，如切换数据/视图）。 */
  onSwitch?: () => void
  /** 空间布局应用（窗口定位）。resize 收敛时也会调用。 */
  layout?: () => void
}

export interface CinemaHandle {
  readonly phase: CinemaPhase
  /** Interactive Gate：resolve 于 240ms（'gate'）或提前 cancel/finish。 */
  readonly whenInteractive: Promise<'gate' | 'cancelled' | 'finished'>
  /** 完全稳定：resolve 于 560ms 或提前收敛。 */
  readonly stable: Promise<'stable' | 'cancelled' | 'finished'>
  /** 中途取消：立即应用最终布局（Final State Override）。 */
  cancel(): void
  /** 立即完成：跳到稳定态。 */
  finish(): void
  /** 宿主尺寸变化：取消空间动画 → 重算布局 → 快速收敛。 */
  notifyResize(): void
  /** 阶段trace（Test 3/4 断言用）。 */
  readonly trace: CinemaTraceEntry[]
}

interface Timer {
  id: number
  phase: CinemaPhase
}

export function startCinema(opts: CinemaOptions = {}): CinemaHandle {
  const t0 = performance.now()
  const trace: CinemaTraceEntry[] = [{ phase: 'begin', t: 0 }]
  let phase: CinemaPhase = 'begin'
  let done = false
  let resizeSeen = false

  const timers: Timer[] = []
  const listeners: Array<() => void> = []
  let resolveGate!: (r: 'gate' | 'cancelled' | 'finished') => void
  let resolveStable!: (r: 'stable' | 'cancelled' | 'finished') => void
  const whenInteractive = new Promise<'gate' | 'cancelled' | 'finished'>((r) => {
    resolveGate = r
  })
  const stable = new Promise<'stable' | 'cancelled' | 'finished'>((r) => {
    resolveStable = r
  })

  function at(ms: number, phaseName: CinemaPhase, fn: () => void): void {
    const id = window.setTimeout(() => {
      if (done) return
      phase = phaseName
      trace.push({ phase: phaseName, t: Math.round(performance.now() - t0) })
      fn()
    }, ms)
    timers.push({ id, phase: phaseName })
  }

  function clearTimers(): void {
    for (const t of timers) window.clearTimeout(t.id)
    timers.length = 0
  }

  function onResize(): void {
    if (done) return
    resizeSeen = true
    handle.notifyResize()
  }
  window.addEventListener('resize', onResize)
  listeners.push(() => window.removeEventListener('resize', onResize))

  function settle(gateResult: 'cancelled' | 'finished', stableResult: 'cancelled' | 'finished'): void {
    if (done) return
    done = true
    clearTimers()
    for (const fn of listeners) fn()
    resolveGate(gateResult)
    resolveStable(stableResult)
  }

  // ---- 时间轴（§十四） ----
  at(CINEMA.switch, 'switch', () => opts.onSwitch?.())
  at(CINEMA.positioning, 'positioning', () => opts.layout?.())
  at(CINEMA.gate, 'gate', () => resolveGate('gate')) // 240ms：交互恢复，此后不阻塞操作
  at(CINEMA.stable, 'stable', () => {
    phase = 'stable'
    trace.push({ phase: 'stable', t: Math.round(performance.now() - t0) })
    settle('finished', 'finished')
  })

  const handle: CinemaHandle = {
    get phase(): CinemaPhase {
      return phase
    },
    whenInteractive,
    stable,
    trace,
    cancel(): void {
      trace.push({ phase: 'cancelled', t: Math.round(performance.now() - t0) })
      phase = 'cancelled'
      // Final State Override：立即落到最终布局，不留半成品。
      try {
        opts.layout?.()
      } catch {
        /* 布局回调自身的异常不阻塞收敛 */
      }
      settle('cancelled', 'cancelled')
    },
    finish(): void {
      try {
        opts.layout?.()
      } catch {
        /* 同上 */
      }
      phase = 'stable'
      trace.push({ phase: 'stable', t: Math.round(performance.now() - t0) })
      settle('finished', 'finished')
    },
    notifyResize(): void {
      if (done) return
      // §十四：取消空间动画 → 重新计算最终布局 → 快速收敛。
      clearTimers()
      try {
        opts.layout?.()
      } catch {
        /* 同上 */
      }
      trace.push({
        phase: 'stable',
        t: Math.round(performance.now() - t0),
      })
      phase = 'stable'
      if (!resizeSeen) {
        /* 直接调用 notifyResize 也走同一条快速收敛路径 */
      }
      resolveGate('gate') // Gate 已达即视为已达（快速收敛不回退交互权）
      resolveStable('stable')
      done = true
      for (const fn of listeners) fn()
    },
  }

  return handle
}
