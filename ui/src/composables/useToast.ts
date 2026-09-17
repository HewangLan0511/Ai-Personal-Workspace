/**
 * Toast Service（TECH-03-B §二）—— 全应用**唯一**的短提示出口。
 *
 * ## 解决什么
 * 接线前有三套各写各的实现：`ModeView`（`.mv-toast`）、`SoftwareView`（`.apps-toast`）、
 * `SettingsView`（`.saved-toast`）。各自持有 `ref` + `setTimeout` + 自己的 DOM 与 CSS，
 * 于是"提示时长/是否单条/怎么显示"三处规则迟早漂移，且没有任何一处能被别的模块复用。
 *
 * 现在只有一个来源：
 *
 * ```
 *   调用方 ──toast.success/error/info(msg)──> 本模块（state：单条 + 4000ms）
 *                                                └─> ToastHost.vue（唯一的渲染者）
 * ```
 *
 * ## 视觉契约：**变体只进数据，暂不进样式**
 * `success/error/info` 会如实记进 `state.variant`，并作为 `data-variant` 挂到宿主元素上，
 * 供将来（IP1 浮层统一 / Skin）按变体着色。**本轮所有变体沿用同一套 canonical 外观** ——
 * 即 `ModeView`/`SoftwareView` 接线前的固定底部居中样式，所以这两页**视觉零变化**。
 * 刻意不在这里新增颜色规则：本轮的原则是"已有视觉不变"。
 *
 * ## canonical 形态（取自接线前的现有行为，不是新设计）
 * 固定底部居中（`bottom:24px; left:50%`）、`--panel` 底 + `--border` 边 + 8px 圆角 +
 * `--shadow`、`z-index:60`、**4000ms 自动消失**、**同一时刻只显示一条**（新的顶掉旧的）。
 */

import { readonly, ref } from 'vue'

/** 提示变体。只影响数据与 `data-variant`，本轮不影响外观。 */
export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastShowOptions {
  /** 显示时长（ms）。默认 4000（与 ModeView / SoftwareView 接线前一致）。 */
  duration?: number
  variant?: ToastVariant
}

export interface ToastState {
  /** 递增序号：同一条文案连续弹两次也能被观察者区分。 */
  id: number
  message: string
  variant: ToastVariant
  /** 本轮固定为 'canonical'；留给将来"内联提示"等其它呈现形态。 */
  presentation: 'canonical'
}

/** 默认时长 —— 与接线前 ModeView / SoftwareView 的 4000ms 一致。 */
export const TOAST_DEFAULT_DURATION = 4000

const state = ref<ToastState | null>(null)
let seq = 0
let timer: ReturnType<typeof setTimeout> | undefined

/** 当前提示（只读响应式）。`null` = 没有提示在显示。 */
export const currentToast = readonly(state)

/** 供非 Vue 环境（验收脚本 / 服务层）订阅。 */
const listeners = new Set<(t: ToastState | null) => void>()

function emit(): void {
  const snapshot = state.value ? { ...state.value } : null
  for (const fn of Array.from(listeners)) {
    try {
      fn(snapshot)
    } catch {
      /* 单个订阅者抛错不得影响其余订阅者 */
    }
  }
}

function clearTimer(): void {
  if (timer !== undefined) {
    clearTimeout(timer)
    timer = undefined
  }
}

/**
 * 显示一条提示。**同一时刻只有一条**：新的直接顶掉旧的（并重置计时），
 * 这与接线前 ModeView / SoftwareView 的 `clearTimeout` + 覆盖语义一致。
 */
export function showToast(message: string, opts: ToastShowOptions = {}): ToastState | null {
  const text = String(message ?? '').trim()
  // 空文案不弹 —— 避免出现一个"没有内容的空框"
  if (!text) return null

  clearTimer()
  seq += 1
  const next: ToastState = {
    id: seq,
    message: text,
    variant: opts.variant ?? 'info',
    presentation: 'canonical',
  }
  state.value = next

  const duration = opts.duration ?? TOAST_DEFAULT_DURATION
  if (duration > 0) {
    timer = setTimeout(() => {
      // 只有"还是我这条"才清 —— 否则会把后来者的提示误清掉
      if (state.value?.id === next.id) {
        state.value = null
        emit()
      }
      timer = undefined
    }, duration)
  }
  emit()
  return { ...next }
}

/** 主动收起当前提示。 */
export function dismissToast(): void {
  clearTimer()
  if (state.value !== null) {
    state.value = null
    emit()
  }
}

export function subscribeToast(fn: (t: ToastState | null) => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** 三个语义化入口（TECH-03-B §二 要求的统一 API）。 */
export const toast = {
  success: (message: string, opts: Omit<ToastShowOptions, 'variant'> = {}): ToastState | null =>
    showToast(message, { ...opts, variant: 'success' }),
  error: (message: string, opts: Omit<ToastShowOptions, 'variant'> = {}): ToastState | null =>
    showToast(message, { ...opts, variant: 'error' }),
  info: (message: string, opts: Omit<ToastShowOptions, 'variant'> = {}): ToastState | null =>
    showToast(message, { ...opts, variant: 'info' }),
  show: showToast,
  dismiss: dismissToast,
  subscribe: subscribeToast,
  /** 当前提示（只读）。 */
  current: currentToast,
}

/** 组合式取用（组件里 `const t = useToast()`）。 */
export function useToast(): typeof toast {
  return toast
}
