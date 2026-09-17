/**
 * 布局与窗口 API 封装（阶段3 / 07-阶段指令-窗口管理）。
 *
 * 通道：Tauri invoke 为主，HTTP `/api/v1/*` 为备用（非浏览器客户端）。
 *
 * ⚠️ **浏览器里没有窗口能力**：`apply` / `place` / `activate` 在非 Tauri 环境下
 * 直接抛 `NativeOnlyError`，而不是假装成功 —— 07 §验收看重"窗口真的动了"，
 * 静默失败会让人以为布局生效了。
 */

import { inTauri, invokeCore, request } from './client'

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface Slot {
  app: string
  rect: Rect
  z: number
  alwaysOnTop?: boolean
  maximized?: boolean
}

export interface AiSidebar {
  enabled: boolean
  edge: string
  width: number
}

export interface Layout {
  name: string
  description?: string | null
  monitor: number
  slots: Slot[]
  aiSidebar?: AiSidebar | null
}

export interface MonitorInfo {
  index: number
  x: number
  y: number
  w: number
  h: number
  work_x: number
  work_y: number
  work_w: number
  work_h: number
  primary: boolean
}

export interface SlotOutcome {
  app: string
  status: 'placed' | 'skipped_not_running' | 'skipped_no_window' | 'failed' | string
  hwnd: number | null
  rect: Rect | null
  reason: string | null
}

export interface ApplyOutcome {
  layout: string
  monitor: number
  degraded_monitor: boolean
  work: Rect
  placed: number
  skipped: number
  failed: number
  slots: SlotOutcome[]
  took_ms: number
}

export interface WindowInfo {
  hwnd: number
  title: string
  class_name: string
  pid: number
  visible: boolean
  minimized: boolean
  maximized: boolean
  rect: Rect | null
  area: number
}

export class NativeOnlyError extends Error {
  constructor(action: string) {
    super(`「${action}」需要桌面端运行（浏览器预览没有窗口控制能力）`)
    this.name = 'NativeOnlyError'
  }
}

export async function list(): Promise<Layout[]> {
  if (inTauri()) {
    return invokeCore<Layout[]>('layouts_list')
  }
  return request<Layout[]>('/api/v1/layouts')
}

export async function monitors(): Promise<MonitorInfo[]> {
  if (inTauri()) {
    return invokeCore<MonitorInfo[]>('monitors_list')
  }
  return request<MonitorInfo[]>('/api/v1/monitors')
}

export async function apply(name: string, monitor?: number): Promise<ApplyOutcome> {
  if (inTauri()) {
    return invokeCore<ApplyOutcome>('layout_apply', { name, monitor: monitor ?? null })
  }
  try {
    return await request<ApplyOutcome>(`/api/v1/layouts/${encodeURIComponent(name)}/apply`, {
      method: 'POST',
    })
  } catch {
    throw new NativeOnlyError('应用布局')
  }
}

export async function windows(pid?: number, title?: string): Promise<WindowInfo[] | WindowInfo | null> {
  if (inTauri()) {
    return invokeCore<WindowInfo[] | WindowInfo | null>('windows_find', {
      pid: pid ?? null,
      title: title ?? null,
    })
  }
  const qs = new URLSearchParams()
  if (pid) qs.set('pid', String(pid))
  if (title) qs.set('title', title)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<WindowInfo[] | WindowInfo | null>(`/api/v1/windows${suffix}`)
}

export async function windowRect(hwnd: number): Promise<Rect | null> {
  if (inTauri()) {
    return invokeCore<Rect | null>('windows_rect', { hwnd })
  }
  return request<Rect | null>(`/api/v1/windows/${hwnd}`)
}

export async function place(hwnd: number, rect: Rect, maximized = false): Promise<Rect> {
  if (inTauri()) {
    return invokeCore<Rect>('windows_place', { hwnd, rect, maximized })
  }
  return request<Rect>(`/api/v1/windows/${hwnd}`, {
    method: 'POST',
    body: JSON.stringify({ ...rect, maximized }),
  })
}

export async function activate(hwnd: number): Promise<{ hwnd: number; foreground: boolean }> {
  if (inTauri()) {
    return invokeCore<{ hwnd: number; foreground: boolean }>('windows_activate', { hwnd })
  }
  return request<{ hwnd: number; foreground: boolean }>(`/api/v1/windows/${hwnd}/activate`, {
    method: 'POST',
  })
}

/**
 * 全部可管理顶层窗口（TECH-07-C Workspace Runtime Adapter 专用）。
 * 与 windows() 的区别：Tauri 侧走独立的 `windows_list` 命令（语义就是"列出全部"），
 * 不经过按 pid/标题查找的 `windows_find`——adapter 边界把 windows_find 列入黑名单。
 */
export async function windowsList(): Promise<WindowInfo[]> {
  if (inTauri()) {
    return invokeCore<WindowInfo[]>('windows_list')
  }
  return request<WindowInfo[]>('/api/v1/windows')
}

export const layoutApi = { list, monitors, apply, windows, windowsList, windowRect, place, activate }
