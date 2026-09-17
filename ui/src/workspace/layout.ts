/**
 * Workspace Runtime —— Layout Snapshot 能力（TECH-02 §三）
 *
 * ## 解决什么
 * UI-05-B 的风险是「模板与工作空间**浅绑定**」：模板只存了"有哪些应用"，
 * 没存"它们摆在哪"，于是每次进入工作空间窗口位置都是随机的。
 * 本模块给模板补上**布局快照**，使「模板 → 工作空间」是**深绑定**。
 *
 * ## 只碰 DOM，绝不碰系统
 * 保存的是**当前 DOM 几何**：`{appId, x, y, width, height, zIndex}`（§三 指定的六个字段）。
 * 不调用任何窗口 API、不 import `@/api/*`、不落库（快照活在 `store.ts` 的内存 `Map` 里）。
 *
 * ## DOM 契约（UI 必须遵守）
 * ```
 * [data-wwr-canvas]                        ← 坐标系原点（position: relative，无 padding/border 更稳）
 *   └─ [data-app-id="<appId>"]             ← 每个应用窗口；若为绝对定位，left/top 即快照 x/y
 * ```
 * 这条契约是 UI ↔ Runtime 之间**唯一**的布局接口。UI 换皮/换布局实现都不影响本模块。
 *
 * ## 坐标系
 * 快照坐标 = 窗口矩形相对 **canvas 内容盒左上角** 的偏移（像素，取整）。
 * 恢复时按同一基准写回 `left/top/width/height/zIndex`，因此往返是自洽的。
 */

import {
  bindSnapshot,
  clearSnapshotsFor,
  findSnapshot,
  getSnapshot,
  listSnapshots,
  newSnapshotId,
  putSnapshot,
  type LayoutSnapshot,
  type LayoutSnapshotEntry,
} from './store'

/** 画布选择器（DOM 契约）。 */
export const CANVAS_SELECTOR = '[data-wwr-canvas]'

/** 窗口元素选择器（DOM 契约）。 */
export const WINDOW_SELECTOR = '[data-wwr-canvas] [data-app-id]'

function canvasEl(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  return document.querySelector<HTMLElement>(CANVAS_SELECTOR)
}

/** canvas 内容盒左上角的视口坐标 —— 绝对定位子元素的 `left/top` 就是相对它算的。 */
function canvasOrigin(canvas: HTMLElement): { x: number; y: number } {
  const r = canvas.getBoundingClientRect()
  return { x: r.left + canvas.clientLeft, y: r.top + canvas.clientTop }
}

/**
 * 采集当前 DOM 几何，保存为布局快照，并把当前工作空间的 layout 标为 `manual`。
 *
 * @param workspaceId 省略则取当前工作空间；两者都没有时返回 `null`（不猜）。
 * @returns 冻结的快照；没有画布 / 没有工作空间 / 画布内没有窗口时返回 `null`。
 */
export function saveLayoutSnapshot(workspaceId?: string): LayoutSnapshot | null {
  const canvas = canvasEl()
  if (!canvas) return null
  const wsId = workspaceId ?? getSnapshot()?.workspaceId
  if (!wsId) return null

  const origin = canvasOrigin(canvas)
  const els = Array.from(canvas.querySelectorAll<HTMLElement>('[data-app-id]'))
  const entries: LayoutSnapshotEntry[] = []
  els.forEach((el, index) => {
    const appId = el.dataset.appId
    if (!appId) return
    const r = el.getBoundingClientRect()
    const rawZ = Number.parseInt(getComputedStyle(el).zIndex, 10)
    entries.push({
      appId,
      x: Math.round(r.left - origin.x),
      y: Math.round(r.top - origin.y),
      width: Math.round(r.width),
      height: Math.round(r.height),
      zIndex: Number.isFinite(rawZ) ? rawZ : index + 1,
    })
  })
  if (!entries.length) return null

  return putSnapshot({
    snapshotId: newSnapshotId(),
    workspaceId: wsId,
    createdAt: Date.now(),
    entries,
  })
}

/**
 * 把快照里的几何写回 DOM（不校验来源，纯写入）。
 * 单独导出是为了让 UI 在**重渲染后**能重放一次 —— 保证 DOM 与快照不脱节。
 */
export function applyLayoutToDom(snapshot: LayoutSnapshot): number {
  const canvas = canvasEl()
  if (!canvas) return 0
  let applied = 0
  for (const e of snapshot.entries) {
    const el = canvas.querySelector<HTMLElement>(`[data-app-id="${e.appId}"]`)
    if (!el) continue
    el.style.left = `${e.x}px`
    el.style.top = `${e.y}px`
    el.style.width = `${e.width}px`
    el.style.height = `${e.height}px`
    el.style.zIndex = String(e.zIndex)
    applied += 1
  }
  return applied
}

/**
 * 恢复布局快照：写回 DOM + 把当前工作空间的 layout 绑定到该快照。
 *
 * @returns 冻结的快照；`snapshotId` 不存在时返回 `null`（不静默兜底）。
 */
export function loadLayoutSnapshot(snapshotId: string): LayoutSnapshot | null {
  const snap = findSnapshot(snapshotId)
  if (!snap) return null
  applyLayoutToDom(snap)
  return bindSnapshot(snapshotId) ?? snap
}

/**
 * 清除某工作空间的布局快照，layout 回落成 `auto`。
 * 注意：DOM 复位由 UI 负责（UI 才知道"自动布局"该长什么样）；本函数只清数据。
 *
 * @returns 被清除的快照条数。
 */
export function clearLayoutSnapshot(workspaceId?: string): number {
  const wsId = workspaceId ?? getSnapshot()?.workspaceId
  if (!wsId) return 0
  return clearSnapshotsFor(wsId)
}

/** 列出某工作空间（省略 = 当前）的全部布局快照。 */
export function listLayoutSnapshots(workspaceId?: string): LayoutSnapshot[] {
  const wsId = workspaceId ?? getSnapshot()?.workspaceId
  return listSnapshots(wsId)
}

/** 按 id 取快照（只读）。 */
export function getLayoutSnapshot(snapshotId: string): LayoutSnapshot | null {
  return findSnapshot(snapshotId)
}
