/**
 * TECH-01 · Interrupt Guard（§十二）。
 *
 * 所有非瞬时动画必须可被中断，中断后快速收敛到最终状态：
 *  - cancel()：立即停在当前帧并清理（用于"让位"场景）；
 *  - finish()：立即跳到最终帧（用于 latest-wins / 让位收敛）；
 *  - 最大生命周期 = duration + FORCE_FINISH_EXTRA，超时强制收敛，
 *    不允许出现"动画 Promise 永远不结束"（§十二硬规则）。
 *
 * 实现基于 WAAPI（Element.animate）：原生可中断，finish/cancel 语义
 * 与 Guard 规则一一对应。
 */

import { FORCE_FINISH_EXTRA } from './config'

export type AnimOutcome = 'completed' | 'forced' | 'cancelled'

export interface InterruptibleAnim {
  /** 结束时 resolve 恰好一次：completed（自然/手动 finish）/ forced（超时收敛）/ cancelled。 */
  readonly finished: Promise<AnimOutcome>
  cancel(): void
  finish(): void
}

export interface AnimOptions {
  duration: number
  easing?: string
  fill?: FillMode
  /** 动画 id（WAAPI，调试/测试定位用）。 */
  id?: string
}

function commitAndCleanup(anim: Animation): void {
  try {
    // fill:'forwards' 的最终值先固化到 style，再撤销动画，避免 effect 堆积。
    ;(anim as Animation & { commitStyles?: () => void }).commitStyles?.()
  } catch {
    /* 元素可能已脱离文档，忽略 */
  }
  anim.cancel()
}

export function runInterruptible(
  el: Element,
  keyframes: Keyframe[] | PropertyIndexedKeyframes,
  opts: AnimOptions,
): InterruptibleAnim {
  const anim = el.animate(keyframes, {
    duration: opts.duration,
    easing: opts.easing,
    fill: opts.fill ?? 'forwards',
    id: opts.id,
  })

  let settled = false
  let resolveFn!: (r: AnimOutcome) => void
  const finished = new Promise<AnimOutcome>((r) => {
    resolveFn = r
  })
  const settle = (r: AnimOutcome): void => {
    if (settled) return
    settled = true
    window.clearTimeout(timeout)
    resolveFn(r)
  }

  anim.onfinish = () => {
    commitAndCleanup(anim)
    settle('completed')
  }
  anim.oncancel = () => settle('cancelled')

  // Interrupt Guard：超时强制收敛，Promise 不悬挂。
  const timeout = window.setTimeout(() => {
    commitAndCleanup(anim)
    settle('forced')
  }, opts.duration + FORCE_FINISH_EXTRA)

  return {
    finished,
    cancel(): void {
      anim.cancel() // oncancel → settle('cancelled')
    },
    finish(): void {
      try {
        anim.finish() // onfinish → commit + cancel + settle('completed')
      } catch {
        // 已结束/未开始的 finish() 会抛 InvalidStateError —— 结果状态一致即可。
        anim.cancel()
      }
    },
  }
}
