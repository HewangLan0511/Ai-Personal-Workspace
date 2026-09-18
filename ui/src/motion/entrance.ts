/**
 * 页面元素进出场（Entrance）· 设计稿 `playEntrance()` 逐值移植
 * ==============================================================
 *
 * 来源 = `personal-workspace-ui/index.html` §`playEntrance`（`ROUTES.home` 首屏入场）。
 *
 * 设计稿原文口径（**三处都是刻意的，不是随手写的**）：
 *   ① 每个元素的时长按"区块身份"取 token：
 *        `data-enter="hero"` → `--mt-dur-entrance`
 *        `data-enter="ws"`   → `--mt-dur-entrance-ws`
 *        其余                → `--mt-dur-entrance-2`
 *      —— 于是"最有分量的那块慢一点、次要的快一点"，错峰来自语义而不是下标。
 *   ② **整段总时长被夹在 400–520ms**：`total = clamp(maxDur * 2, 400, 520)`，
 *      再用 `step = (total - maxDur) / (n - 1)` 反推步长。
 *      这样首屏有 3 块还是 6 块，整段入场都稳定在 400–520ms 内 —— 不会区块一多
 *      就拖成 1 秒的"入场表演"。这是本动效最容易被改坏的一条。
 *   ③ 动画本身**不在这里定义**：`.enter-up`（base.css 的 UI-FUSION-FULL 段）
 *      负责位移与不透明度，且幅度走 `--mt-fade-from` / `--mt-dist-item`
 *      —— reduced/off 档自动降级；`maxDur < 20ms` 时（off 档）直接不播。
 *
 * ★ 与设计稿的一处**有意差异**（已登记）：
 *   设计稿只在**首页第一次进入**播放（`homeEntered` 一次性标志）。本工程把同一套
 *   编排用于首页 / 档案 / 设置 / 软件四个页面，且**每次进入都播**（列表页内容会变，
 *   只在第一次播等于之后都看不到）。首页保留设计稿的"每会话只播一次"语义 ——
 *   首屏入场是一次"欢迎编排"，反复重播会变成噪音。
 *   两处共用同一份 token / 类名 / 步长公式，风格仍然统一。
 */

import { nextTick, onMounted, type Ref } from 'vue'

import { motionMs } from './runtime'
import { getMotionLevel } from './guards'

/** 区块身份 → 时长 token（设计稿 `durOf`）。 */
const DUR_TOKEN: Record<string, string> = {
  hero: '--mt-dur-entrance',
  ws: '--mt-dur-entrance-ws',
}
const DUR_TOKEN_DEFAULT = '--mt-dur-entrance-2'
const DUR_FALLBACK = 200

/** 总时长夹取区间（设计稿硬编码的 400 / 520，属**编排参数**，不是可用性 token）。 */
const TOTAL_MIN = 400
const TOTAL_MAX = 520

/** 已播过的"一次性"入场（设计稿 `homeEntered`）。按 key 记账，允许同页多次挂载不重播。 */
const played = new Set<string>()

function durOf(el: HTMLElement): number {
  const kind = el.dataset['enter'] || ''
  return motionMs(DUR_TOKEN[kind] ?? DUR_TOKEN_DEFAULT, DUR_FALLBACK)
}

/**
 * 对 `root` 内所有 `[data-enter]` 播一次入场。
 *
 * @param root 页面根元素（`[data-enter]` 的直接/间接父节点）
 * @returns 实际参与播放的元素个数（0 = 没播：off 档 / 无元素 / 时长归零）
 */
export function playEntrance(root: HTMLElement | null | undefined): number {
  if (!root) return 0
  const els = Array.from(root.querySelectorAll<HTMLElement>('[data-enter]'))
  if (!els.length) return 0

  const durs = els.map(durOf)
  const maxDur = Math.max(...durs)
  // off / reduced（时长归零）→ 直接到位，不挂类不等待
  if (!(maxDur >= 20)) return 0

  const total = Math.min(Math.max(maxDur * 2, TOTAL_MIN), TOTAL_MAX)
  const step = els.length > 1 ? (total - maxDur) / (els.length - 1) : 0

  els.forEach((el, i) => {
    el.classList.remove('enter-up')
    el.style.animationDuration = `${durs[i]}ms`
    el.style.animationDelay = `${Math.round(step * i)}ms`
    void el.offsetWidth // 强制重排，保证连续两次调用都能重播
    el.classList.add('enter-up')
  })

  // ★ 刻意**没有**"动画放完后摘类 + 清内联"的收尾定时器（这里曾有一版，已删）。
  //
  // 为什么删：入场是一次性 CSS 动画，`.enter-up` 的 `animation-fill-mode: both`
  // 让它停在终态，DOM 上留着类与内联时长**不影响任何视觉**；而收尾定时器会在
  // 页面"看起来已经静默"之后的 500ms 左右再写一轮 DOM（摘类 + 清两条内联），
  // 这一轮写会被以"静默 250ms 为对照、再切皮肤 250ms 为实验"的
  // **零 render 探针**（`verify_skin_engine` T6：非 root 属性变更必须是空集）
  // 判成"切皮肤触发了渲染" —— 实际是入场收尾落在了观测窗口里。
  // 收尾本身没有任何收益（终态由 fill-mode 保证），却能把一个真实的架构断言
  // 打成假红，所以宁可不做。
  //
  // 重播语义不受影响：`.enter-up` 在每次调用开头先摘再加（配 `offsetWidth` 强制重排），
  // 页面重新挂载时元素本身是新的，动画自然重头播。
  return els.length
}

export interface UsePageEntranceOptions {
  /**
   * 一次性：整会话只播一次（设计稿首页 `homeEntered` 的语义）。
   * `key` 用于记账，默认取 `once` 的取值本身。
   */
  once?: boolean
  /** 一次性记账的 key（同一页面可能要分不同场景播，避免互相顶掉）。 */
  key?: string
}

/**
 * 组合式封装：页面挂载（DOM 就位）后播一次入场。
 *
 * 为什么等 `nextTick`：`onMounted` 时子组件的 DOM 还没全部插入，
 * 直接查 `[data-enter]` 会漏掉后挂载的区块（设计稿是 innerHTML 一次性写入，没这个问题）。
 */
export function usePageEntrance(
  root: Ref<HTMLElement | null>,
  opts: UsePageEntranceOptions = {},
): void {
  onMounted(async () => {
    await nextTick()
    if (getMotionLevel() === 'off') return
    const key = opts.key ?? 'page'
    if (opts.once) {
      if (played.has(key)) return
      played.add(key)
    }
    playEntrance(root.value)
  })
}

/** 测试/调试用：清掉"一次性"记账（重新进入会话语义）。 */
export function resetEntranceHistory(): void {
  played.clear()
}
