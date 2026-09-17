/**
 * TECH-01 · Page Transition Runtime（§十五）。
 *
 * Content-only 过渡：
 *   old: opacity 1→0, Y 0→-2（×intensity）
 *   new: opacity 0→1, Y +4→0（×intensity）
 * 默认 out 160ms / in 200ms（spec 160–220ms 区间）。
 *
 * latest-wins（§十五）：A→B→C→D 连续导航只保留最终 D——
 * 每次新 enter 递增世代号，并把所有更老世代的在飞动画 finish()
 * （跳到最终帧、立即触发 done），不允许中间状态残留。
 *
 * 幅度 ×intensity、时长固定 —— Duration 与 Intensity 解耦（§七）。
 */

import { PAGE_TRANSITION } from './config'
import { getMotionLevel, intensity } from './guards'
import { runInterruptible, type InterruptibleAnim } from './interrupt'

interface RunningAnim {
  gen: number
  anim: InterruptibleAnim
}

let gen = 0
const running = new Set<RunningAnim>()

function killOlderThan(g: number): void {
  for (const rec of [...running]) {
    if (rec.gen < g) {
      // finish → 跳到最终帧（最终态覆写，§十四 Final State Override），
      // onfinish 链会触发 Vue 的 done 回调并从 running 清除。
      rec.anim.finish()
      running.delete(rec)
    }
  }
}

export interface PageTransitionHooks {
  onEnter(el: Element, done: () => void): void
  onLeave(el: Element, done: () => void): void
}

export function createPageTransitionHooks(): PageTransitionHooks {
  return {
    onEnter(el: Element, done: () => void): void {
      const g = ++gen
      killOlderThan(g)
      if (getMotionLevel() === 'off') {
        done()
        return
      }
      const i = intensity()
      const anim = runInterruptible(
        el,
        [
          { opacity: 0, transform: `translateY(${4 * i}px)` },
          { opacity: 1, transform: 'translateY(0px)' },
        ],
        { duration: PAGE_TRANSITION.inMs, easing: 'cubic-bezier(0, 0, 0.2, 1)', id: 'pw-page-in' },
      )
      const rec: RunningAnim = { gen: g, anim }
      running.add(rec)
      void anim.finished.then(() => {
        running.delete(rec)
        done()
      })
    },

    onLeave(el: Element, done: () => void): void {
      if (getMotionLevel() === 'off') {
        done()
        return
      }
      const i = intensity()
      // 离场页浮出文档流，避免与新页互相挤压（App.vue 的 .app-main 已设 relative）。
      const host = el as HTMLElement
      host.style.position = 'absolute'
      host.style.inset = '0'
      const anim = runInterruptible(
        el,
        [
          { opacity: 1, transform: 'translateY(0px)' },
          { opacity: 0, transform: `translateY(${-2 * i}px)` },
        ],
        { duration: PAGE_TRANSITION.outMs, easing: 'cubic-bezier(0.4, 0, 1, 1)', id: 'pw-page-out' },
      )
      const rec: RunningAnim = { gen, anim }
      running.add(rec)
      void anim.finished.then(() => {
        running.delete(rec)
        done()
      })
    },
  }
}

/** 测试/调试用：当前是否还有在飞的页面过渡动画。 */
export function hasPendingPageAnims(): boolean {
  return running.size > 0
}
