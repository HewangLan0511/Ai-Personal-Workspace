/**
 * 右键菜单（设计稿 `ctxMenu()` / `closeCtx()` 的组件化移植）
 * =================================================================
 *
 * 唯一来源 = `personal-workspace-ui/index.html` line 1266–1288 + 5026–5061。
 *
 * 设计稿的三条行为，逐条搬过来：
 *   1) **跟随鼠标 + 自动避开视口边界**：`left = min(x, innerWidth - boxW - 8)`、
 *      `top = min(y, innerHeight - boxH - 8)`，`boxW = 200`、`boxH = 条目数 * 34 + 12`
 *      —— 定值是设计稿的，不改。
 *   2) **点外部 / 滚轮 / Esc 都关**：`mousedown`（目标不在 `.ctx-menu` 内）、
 *      `wheel`（passive）、Esc。三者与设计稿同一优先级顺序。
 *   3) **退场先播 `.out` 再移除**：直接移除会让弹层"啪"地消失，动画根本没机会播
 *      （设计稿 `closeLayer()` 的原话）。时长取 `--mt-dur-ctx`；`reduced/off`
 *      档位下该 token 归零 → 直接清空，不留空等。
 *
 * ★ 为什么是单例而不是每个调用点一份：菜单是"同一时刻至多一个"的浮层，
 *   与设计稿把 `#ctxMenu` 挂在 body 上是同一口径（多次打开 = 先关旧的）。
 * ★ 为什么内部归一成带 `kind` 的扁平结构：设计稿的 items 是"字符串/对象混排"的
 *   动态数组，直接照抄到 TS 会在模板里到处需要类型收窄。调用方仍写设计稿那种
 *   简写（`{icon,label}` / `'sep'` / `{head}`），归一在 `open()` 里做一次。
 */

import { reactive } from 'vue'

import { motionMs } from '@/motion'

/** 调用方写的条目（设计稿形态）。 */
export interface CtxMenuItemInput {
  icon?: string
  label: string
  danger?: boolean
  disabled?: boolean
  /** 快捷键提示（设计稿 `.kbd`）。 */
  kbd?: string
  /** 选中回调（设计稿的 `data-act` + 全局 click 委托，这里直接给函数）。 */
  onSelect?: () => void
}

/** 调用方写的 items 数组（设计稿三种形态混排）。 */
export type CtxEntryInput = CtxMenuItemInput | 'sep' | { head: string }

/** 归一后的内部形态：`kind` 是唯一判别式，模板零类型收窄。 */
export interface CtxEntry {
  kind: 'item' | 'sep' | 'head'
  label: string
  head: string
  icon: string
  kbd: string
  danger: boolean
  disabled: boolean
  onSelect: (() => void) | null
}

interface CtxState {
  open: boolean
  left: number
  top: number
  items: CtxEntry[]
  /** 退场中（`.ctx-menu.out`）：此间不接受新交互，也不重复排定时器。 */
  closing: boolean
}

/** 设计稿定值：菜单盒宽 / 每行高 / 内边距 / 与视口边缘的安全距离。 */
export const BOX_W = 200
export const ROW_H = 34
const BOX_PAD = 12
const VIEWPORT_GAP = 8

const state = reactive<CtxState>({ open: false, left: 0, top: 0, items: [], closing: false })

let outTimer = 0

function clearOutTimer(): void {
  if (outTimer) {
    window.clearTimeout(outTimer)
    outTimer = 0
  }
}

function normalize(it: CtxEntryInput): CtxEntry {
  const base: CtxEntry = {
    kind: 'item',
    label: '',
    head: '',
    icon: '',
    kbd: '',
    danger: false,
    disabled: false,
    onSelect: null,
  }
  if (it === 'sep') return { ...base, kind: 'sep' }
  if (typeof it === 'object' && it !== null && 'head' in it) {
    return { ...base, kind: 'head', head: (it as { head: string }).head }
  }
  const m = it as CtxMenuItemInput
  return {
    ...base,
    kind: 'item',
    label: m.label,
    icon: m.icon ?? '',
    kbd: m.kbd ?? '',
    danger: !!m.danger,
    disabled: !!m.disabled,
    onSelect: m.onSelect ?? null,
  }
}

/** 设计稿 `closeCtx()` + `closeLayer()` 的退场动画分支。 */
export function closeContextMenu(): void {
  if (!state.open || state.closing) return
  const outMs = motionMs('--mt-dur-ctx', 120)
  if (outMs < 20) {
    clearOutTimer()
    state.open = false
    state.closing = false
    state.items = []
    return
  }
  state.closing = true
  clearOutTimer()
  outTimer = window.setTimeout(() => {
    outTimer = 0
    state.open = false
    state.closing = false
    state.items = []
  }, outMs)
}

/**
 * 打开右键菜单。
 * @param x 指针 clientX（设计稿跟随鼠标）
 * @param y 指针 clientY
 * @param items 条目数组（`'sep'` = 分隔线，`{head}` = 分组标题）
 */
export function openContextMenu(x: number, y: number, items: CtxEntryInput[]): void {
  // 设计稿是 `closeCtx()` 后立刻重建（无退场等待）——"先关旧的"不阻塞新的
  clearOutTimer()
  state.closing = false
  const boxH = items.length * ROW_H + BOX_PAD
  state.left = Math.min(x, window.innerWidth - BOX_W - VIEWPORT_GAP)
  state.top = Math.min(y, window.innerHeight - boxH - VIEWPORT_GAP)
  state.items = items.map(normalize)
  state.open = true
}

export interface ContextMenuApi {
  state: CtxState
  open: typeof openContextMenu
  close: typeof closeContextMenu
}

/** 单例访问器（与 `useShellLayout` / `useToast` 同一口径）。 */
let api: ContextMenuApi | null = null

export function useContextMenu(): ContextMenuApi {
  if (!api) api = { state, open: openContextMenu, close: closeContextMenu }
  return api
}
