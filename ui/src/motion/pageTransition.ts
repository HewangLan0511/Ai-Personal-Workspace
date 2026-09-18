/**
 * TECH-01 · Page Transition Runtime（§十五）· UI-FUSION 动效对接版
 * ================================================================
 *
 * Content-only 过渡：只有内容区参与，顶栏 / 侧边栏 / 组件区 / AI 侧栏都不动。
 *
 * ★ 视觉来源 = 设计稿的两个瞬态类（`personal-workspace-ui/index.html`）：
 *     `.scene-out{animation:sceneOut var(--mt-dur-scene-out) var(--mt-ease-in) both}`
 *     `.scene-in {animation:sceneIn  var(--mt-dur-scene-in)  var(--mt-ease-out) both}`
 *   规则在 base.css 的 UI-FUSION-FULL 段（脚本逐字并入）。本模块**只负责编排**：
 *   什么时候挂哪个类、等多久 —— 位移/不透明度/缓动/时长全部由那两条规则给。
 *
 * ★ 为什么从 WAAPI 改成"挂类 + 读 token 等待"：
 *   旧实现把 `translateY(4px→0)`、`160ms / 200ms` 写死在 TS 里，于是
 *     · 幅度不再随 `--mt-intensity` 变（reduced/off 档幅度不降）；
 *     · 时长不再随 Skin 的 `--mt-skin-dur-*` 变（换肤对页面切换无效）；
 *     · 设计稿的 `.scene-in/.scene-out` 成了"有规则、无消费方"的死代码。
 *   现在这两个数字只有一处事实来源（motion-tokens.css），Skin/Guard 都能改档。
 *
 * ★ latest-wins（§十五）：A→B→C→D 连续导航只保留最终 D ——
 *   每次 enter 递增世代号，并把所有更老世代**立即收敛**（摘类 + 立刻 done），
 *   不允许中间状态残留。原型的 `sceneSeq` 是同一件事。
 *
 * ★ Interrupt Guard（§十二）：`done` 绝不悬挂 —— 除 token 时长外再挂一条
 *   `时长 + FORCE_FINISH_EXTRA` 的兜底定时器，超时也一定收敛（否则 Vue 的
 *   离场钩子不回调，会出现"两个页面重叠停在屏幕上"）。
 */

import { FORCE_FINISH_EXTRA } from './config'
import { getMotionLevel } from './guards'
import { motionMs } from './runtime'

/** 稳态超时时长：token 读不到（未挂载/未定义）时的兜底毫秒值（= 设计稿默认值）。 */
const OUT_FALLBACK = 80
const IN_FALLBACK = 140
/** 低于此值视为"动画已被 Guard/Skin 归零" → 直接到位，不做无意义等待。 */
const ZERO_MS = 20

interface Running {
  gen: number
  el: HTMLElement
  cls: string
  done: () => void
  /** 按 token 时长的正表 */
  timer: number
  /** 兜底收敛表（token 时长 + FORCE_FINISH_EXTRA）—— 保证 done 一定被调到 */
  guard: number
}

let gen = 0
const running = new Set<Running>()

/** 立即收敛一条记录：停表 + 摘类 + 回调 done（幂等）。 */
function settle(rec: Running): void {
  window.clearTimeout(rec.timer)
  window.clearTimeout(rec.guard)
  rec.el.classList.remove(rec.cls)
  running.delete(rec)
  rec.done()
}

/** latest-wins：让所有更老世代的过渡立刻到位。 */
function killOlderThan(g: number): void {
  for (const rec of [...running]) {
    if (rec.gen < g) settle(rec)
  }
}

/**
 * 给一个页面元素挂上瞬态类并等待它播完。
 *
 * @param el   页面根元素（Vue 传进来的 `<component :is>` 根节点）
 * @param cls  `scene-in` / `scene-out`
 * @param token 时长 token 名
 * @param fallback token 读不到时的兜底毫秒
 * @param done Vue 的过渡完成回调
 */
function play(el: Element, cls: string, token: string, fallback: number, done: () => void): void {
  // off 档：非必要动画关闭 —— 直接到位（设计稿：`outMs < 20` 时 paint 不挂类）
  if (getMotionLevel() === 'off') {
    done()
    return
  }
  const host = el as HTMLElement
  const g = ++gen
  killOlderThan(g)

  const ms = motionMs(token, fallback)
  if (ms < ZERO_MS) {
    done()
    return
  }

  // 重播保障：同一元素若已带着这个类（例如快速来回切），先摘再强制重排
  host.classList.remove(cls)
  void host.offsetWidth
  host.classList.add(cls)

  const rec: Running = {
    gen: g,
    el: host,
    cls,
    done,
    timer: window.setTimeout(() => settle(rec), ms),
    guard: window.setTimeout(() => settle(rec), ms + FORCE_FINISH_EXTRA),
  }
  running.add(rec)
}

export interface PageTransitionHooks {
  onEnter(el: Element, done: () => void): void
  onLeave(el: Element, done: () => void): void
}

export function createPageTransitionHooks(): PageTransitionHooks {
  return {
    onEnter(el: Element, done: () => void): void {
      play(el, 'scene-in', '--mt-dur-scene-in', IN_FALLBACK, done)
    },

    onLeave(el: Element, done: () => void): void {
      // 离场页浮出文档流，避免与新页互相挤压（App.vue 的 .app-main 已设 relative）。
      const host = el as HTMLElement
      host.style.position = 'absolute'
      host.style.inset = '0'
      play(el, 'scene-out', '--mt-dur-scene-out', OUT_FALLBACK, done)
    },
  }
}

/** 测试/调试用：当前是否还有在飞的页面过渡。 */
export function hasPendingPageAnims(): boolean {
  return running.size > 0
}
