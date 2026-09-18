/**
 * 通用拖拽排序（设计稿 `enableSort` + `flip` + `swapNodes` + `swapSize` 逐值移植）
 * ==========================================================================
 *
 * 唯一来源 = `personal-workspace-ui/index.html` §"通用拖拽排序"。两份模式：
 *   - `move`（默认）：实时让位 —— 拖过邻居时邻居就滑开，不等落点确认；
 *   - `swap`：交换位置并继承对方的**视觉占比**（首页网格用）。
 *
 * ★ 设计稿的两条关键纪律，这里一字不改地保留：
 *   **关键 1：拖拽只在 DOM 上局部换位，绝不触发整页重绘。**
 *     整页重绘 + scrollTop 归零会产生"刷新"的观感。本项目里对应的是：
 *     `dragover` 期间**只动 DOM**，不写任何响应式状态；`drop` 时才回调 `onReorder`
 *     提交数据（调用方负责落库）。于是"拖动过程"与"数据提交"彻底分离。
 *   **关键 2：swap 只交换"尺寸"**，其余参数（明暗度 / 不透明度 / 色调 / 边框 / 动效）
 *     跟着对象本身走，不随槽位互换。实现见 `swapSize` 的白名单制。
 *
 * ★ 时长一律走 token：`--mt-dur-reorder`（`flip`）+ 元素自带 transition。
 *   Motion Guard 把 `--mt-*` 归零后，`flip` 里 `dur < 20` 的分支直接 `mutate()`
 *   一步到位 —— 这正是设计稿的 off/reduced 语义，不是这里另加的特例。
 */

import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

import { motionMs } from '@/motion'

export type SortMode = 'move' | 'swap'

export interface ListSortOptions {
  /** 参与排序的子项选择器，如 `.wcard` */
  itemSelector: string
  mode?: SortMode
  /** 落位回调（`from` → `to`，均为**排序后**索引）。只在 `drop` 时调一次。 */
  onReorder: (from: number, to: number) => void
  /** 静默播报（进 aria-live，不弹可见提示） */
  announce?: (msg: string) => void
}

/** 只交换两个兄弟节点的位置，不重建、不重绘 */
function swapNodes(a: Element, b: Element): void {
  const p = a.parentNode
  if (!p || a === b) return
  const an = a.nextSibling
  const bn = b.nextSibling
  if (an === b) p.insertBefore(b, a)
  else if (bn === a) p.insertBefore(a, b)
  else {
    p.insertBefore(b, an)
    p.insertBefore(a, bn)
  }
}

const SIZE_CLASS_RE = /\bsize-[a-z]+\b/
/** 只影响占位大小的属性；其余（opacity / filter / background …）一律不搬 */
const SIZE_STYLE_PROPS = [
  'grid-column',
  'grid-row',
  'grid-column-start',
  'grid-column-end',
  'grid-row-start',
  'grid-row-end',
  'grid-area',
  'width',
  'height',
  'min-width',
  'min-height',
  'max-width',
  'max-height',
  'flex',
  'flex-grow',
  'flex-basis',
  'aspect-ratio',
]

function swapSize(a: HTMLElement, b: HTMLElement): void {
  if (a === b) return
  const ca = (a.className.match(SIZE_CLASS_RE) || [])[0]
  const cb = (b.className.match(SIZE_CLASS_RE) || [])[0]
  if (ca) a.classList.remove(ca)
  if (cb) b.classList.remove(cb)
  if (cb) a.classList.add(cb)
  if (ca) b.classList.add(ca)
  const va: Record<string, string> = {}
  const vb: Record<string, string> = {}
  for (const p of SIZE_STYLE_PROPS) {
    va[p] = a.style.getPropertyValue(p)
    vb[p] = b.style.getPropertyValue(p)
  }
  for (const p of SIZE_STYLE_PROPS) {
    const pa = a.style.getPropertyPriority(p)
    const pb = b.style.getPropertyPriority(p)
    a.style.removeProperty(p)
    b.style.removeProperty(p)
    if (vb[p]) a.style.setProperty(p, vb[p], pb)
    if (va[p]) b.style.setProperty(p, va[p], pa)
  }
}

/** 重播同一个动画：先摘 class、强制重排、再加回去（否则连续两次不会重播） */
export function once(el: Element | null | undefined, cls: string): void {
  if (!el) return
  el.classList.remove(cls)
  void (el as HTMLElement).offsetWidth
  el.classList.add(cls)
}

/** 交换落位时的描边闪光（设计稿 `.just-swap`） */
export const flash = (el: Element | null | undefined): void => once(el, 'just-swap')

/** 成功：闪一圈描边（设计稿 `okFlash`）。用于"操作被接受"的即时反馈。 */
export const okFlash = (el: Element | null | undefined): void => once(el, 'ok-flash')

/** 错误：小幅横向纠正（设计稿 `errShake`）。用于表单校验失败。 */
export const errShake = (el: Element | null | undefined): void => once(el, 'err-shake')

/** FLIP：先量旧位置 → 改 DOM → 从旧位置动画回新位置；被拖的那个（skip）不参与 */
export function flip(
  nodes: Element[],
  mutate: () => void,
  dur: number,
  skip: Element | null,
): void {
  if (dur < 20 || !nodes.length) {
    mutate()
    return
  }
  const first = new Map<Element, DOMRect>()
  for (const el of nodes) if (el !== skip) first.set(el, el.getBoundingClientRect())
  mutate()
  const moved: Array<[HTMLElement, number, number]> = []
  first.forEach((r0, el) => {
    const r1 = el.getBoundingClientRect()
    const dx = r0.left - r1.left
    const dy = r0.top - r1.top
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) moved.push([el as HTMLElement, dx, dy])
  })
  if (!moved.length) return
  for (const [el, dx, dy] of moved) {
    el.style.transition = 'none'
    el.style.transform = `translate(${dx}px, ${dy}px)`
    el.style.willChange = 'transform'
  }
  requestAnimationFrame(() => {
    for (const [el] of moved) {
      el.style.transition = `transform ${dur}ms var(--mt-ease-out)`
      el.style.transform = 'translate(0, 0)'
    }
    window.setTimeout(() => {
      for (const [el] of moved) {
        el.style.transition = ''
        el.style.transform = ''
        el.style.willChange = ''
      }
    }, dur + 40)
  })
}

/**
 * 把排序行为挂到一个容器上。
 *
 * 与原型同口径：**行为绑在容器**（`container.querySelectorAll(itemSel)` 逐个挂），
 * 不绑在组件里 —— 容器重绘后新节点重新挂一次即可，不会出现"同一节点两套监听"。
 *
 * @param container 容器元素（`move` 模式下它必须是子项的**直接父节点** ——
 *   设计稿在这里踩过坑：绑错层级会让 `insertBefore` 抛 `NotFoundError`，拖拽静默失效）
 */
export function useListSort(
  container: Ref<HTMLElement | null>,
  opts: ListSortOptions,
): { attach: () => void; detach: () => void } {
  const mode: SortMode = opts.mode ?? 'move'
  let teardown: (() => void) | null = null

  function attach(): void {
    detach()
    const root = container.value
    if (!root) return
    const dur = (): number => motionMs('--mt-dur-reorder', 160)
    const items = (): HTMLElement[] =>
      Array.from(root.querySelectorAll<HTMLElement>(opts.itemSelector))
    const clean = (): void => {
      root.querySelectorAll('.drop-target').forEach((n) => n.classList.remove('drop-target'))
    }

    let src: HTMLElement | null = null
    let originFrom = -1
    let busy = false

    const onDragStart = (e: DragEvent): void => {
      const el = e.currentTarget as HTMLElement
      src = el
      originFrom = items().indexOf(el)
      el.classList.add('dragging')
      // 解除 Hover 优先级：拖拽期间所有 hover 效果让位
      document.body.classList.add('is-dragging')
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move'
        try {
          e.dataTransfer.setData('text/plain', '')
        } catch {
          /* 某些环境只读 dataTransfer：不影响拖拽本身 */
        }
      }
    }

    const onDragEnd = (): void => {
      document.body.classList.remove('is-dragging')
      src?.classList.remove('dragging')
      clean()
      src = null
      originFrom = -1
    }

    const onDragOver = (e: DragEvent): void => {
      const el = e.currentTarget as HTMLElement
      if (!src || src === el) return
      e.preventDefault()
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
      if (mode === 'swap') {
        clean()
        el.classList.add('drop-target')
        return
      }
      /* move：实时让位 —— 邻居 120–180ms 滑开，不等落点确认 */
      if (busy) return // 动画中不排队、不追问
      const list = items()
      const from = list.indexOf(src)
      const to = list.indexOf(el)
      if (from < 0 || to < 0 || from === to) return
      const ref = from < to ? list[to].nextSibling : list[to]
      if (src.nextSibling === ref) return
      busy = true
      flip(list, () => root.insertBefore(src as HTMLElement, ref), dur(), src)
      window.setTimeout(() => {
        busy = false
      }, dur())
    }

    const onDragLeave = (e: DragEvent): void => {
      ;(e.currentTarget as HTMLElement).classList.remove('drop-target')
    }

    const onDrop = (e: DragEvent): void => {
      e.preventDefault()
      const el = e.currentTarget as HTMLElement
      if (!src || src === el) return
      el.classList.remove('drop-target')
      const list = items()
      const to = list.indexOf(el)
      if (mode === 'swap') {
        if (originFrom < 0 || to < 0 || originFrom === to) return
        const A = list[to]
        const B = src
        flip(
          [A, B],
          () => {
            swapNodes(A, B)
            swapSize(A, B)
          },
          dur(),
          null,
        )
        flash(A)
        flash(B)
        opts.onReorder(originFrom, to)
        opts.announce?.(`已与第 ${to + 1} 项交换位置`)
        return
      }
      const finalTo = list.indexOf(src)
      if (originFrom < 0 || finalTo < 0 || originFrom === finalTo) return
      flash(src)
      // 只更新数据与播报，禁止整页重绘
      opts.onReorder(originFrom, finalTo)
      opts.announce?.(`已移动到第 ${finalTo + 1} 位`)
    }

    const bound: Array<[HTMLElement, string, EventListener]> = []
    root.querySelectorAll<HTMLElement>(opts.itemSelector).forEach((el) => {
      el.addEventListener('dragstart', onDragStart)
      el.addEventListener('dragend', onDragEnd)
      el.addEventListener('dragover', onDragOver)
      el.addEventListener('dragleave', onDragLeave)
      el.addEventListener('drop', onDrop)
      bound.push([el, 'dragstart', onDragStart as EventListener])
      bound.push([el, 'dragend', onDragEnd as EventListener])
      bound.push([el, 'dragover', onDragOver as EventListener])
      bound.push([el, 'dragleave', onDragLeave as EventListener])
      bound.push([el, 'drop', onDrop as EventListener])
    })
    teardown = () => {
      for (const [el, type, fn] of bound) el.removeEventListener(type, fn)
      bound.length = 0
      onDragEnd()
    }
  }

  function detach(): void {
    teardown?.()
    teardown = null
  }

  onBeforeUnmount(detach)
  return { attach, detach }
}

/**
 * 便捷包装：把排序挂载收敛成一个"随列表长度变化自动重挂"的引用。
 *
 * 为什么需要自动重挂：`attach()` 是对**当时存在的**子项逐个挂监听，之后新增的
 * `.wcard`（用户打开一个新挂件）不在其中。原型的做法是"重绘后重新 wireDrag()"，
 * 这里用 `watch(itemCount)` 表达同一件事。
 */
export function useAutoSort(
  container: Ref<HTMLElement | null>,
  itemCount: Ref<number>,
  opts: ListSortOptions,
): void {
  const sort = useListSort(container, opts)
  watch(
    [container, itemCount],
    () => {
      void sort.attach()
    },
    { flush: 'post', immediate: true },
  )
}

/** 让"空容器"也能被 watch 到：给调用方一个稳定的元素引用槽 */
export function elementRef(): Ref<HTMLElement | null> {
  return ref<HTMLElement | null>(null)
}
