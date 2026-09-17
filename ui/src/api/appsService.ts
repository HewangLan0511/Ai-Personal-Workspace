/**
 * 软件管理 API 封装（阶段2 / 05-阶段指令-软件管理）。
 *
 * 通道策略与 `configService` 一致：
 *   1. Tauri invoke（`apps_*` 系列）—— 主路径，不受 core 随机端口影响；
 *   2. HTTP `/api/v1/apps/*` —— 仅供非浏览器客户端（curl / 验收脚本）；
 *   3. localStorage —— 浏览器直开（vite dev）时的降级。
 *
 * ⚠️ 降级边界（如实标注，勿误读）：
 *   列表 / 分类 / 增删改在浏览器里可降级到 localStorage（纯数据）；
 *   但 **启动 / 扫描 / 文件选择 / 图标探测依赖原生能力**，浏览器下会**明确抛错**，
 *   而不是静默失败 —— 见 05 §2「失败要可见」。
 */

import { inTauri, invokeCore, request } from './client'
import { logger } from '@/utils/logger'

export interface AppItem {
  id: number
  name: string
  path: string
  args: string
  icon: string | null
  type: string | null
  category: string | null
  launch_count: number
  last_used_at: string | null
  pinned: boolean
  created_at: string
  updated_at: string
}

export interface AppInput {
  name: string
  path: string
  args?: string
  icon?: string | null
  type?: string | null
  category?: string | null
}

export interface AppPatch {
  name?: string
  args?: string
  icon?: string | null
  type?: string | null
  category?: string | null
  pinned?: boolean
}

export interface LaunchResult {
  appId: number
  pid: number | null
  pidTracked: boolean
  alreadyRunning: boolean
}

export interface InstalledApp {
  name: string
  path: string
  installLocation: string
  publisher: string
  version: string
  launchable: boolean
}

const LS_KEY = 'pw.apps'

/** 浏览器降级专用的错误：说明"这个操作需要桌面端"。 */
export class NativeOnlyError extends Error {
  constructor(action: string) {
    super(`「${action}」需要桌面端运行（浏览器预览不具备该原生能力）`)
    this.name = 'NativeOnlyError'
  }
}

// ---------------------------------------------------------------- 列表 / 增删改

export async function list(category?: string, search?: string): Promise<AppItem[]> {
  if (inTauri()) {
    try {
      return await invokeCore<AppItem[]>('apps_list', {
        category: category ?? null,
        search: search ?? null,
      })
    } catch (err) {
      logger.warn('apps', `invoke apps_list 失败，降级 HTTP：${String(err)}`)
    }
  }
  try {
    const qs = new URLSearchParams()
    if (category) qs.set('category', category)
    if (search) qs.set('search', search)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return await request<AppItem[]>(`/api/v1/apps${suffix}`)
  } catch {
    logger.warn('apps', '读取失败，降级 localStorage')
    return filterLocal(readLocal(), category, search)
  }
}

export async function categories(): Promise<string[]> {
  if (inTauri()) {
    try {
      return await invokeCore<string[]>('apps_categories')
    } catch (err) {
      logger.warn('apps', `invoke apps_categories 失败：${String(err)}`)
    }
  }
  try {
    return await request<string[]>('/api/v1/apps/categories')
  } catch {
    const preset = ['开发', '浏览器', '办公', '媒体', '游戏', '其他']
    for (const item of readLocal()) {
      if (item.category && !preset.includes(item.category)) preset.push(item.category)
    }
    return preset
  }
}

export async function add(input: AppInput): Promise<AppItem> {
  if (inTauri()) {
    return invokeCore<AppItem>('apps_add', { input })
  }
  try {
    return await request<AppItem>('/api/v1/apps', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  } catch {
    return addLocal(input)
  }
}

export async function update(id: number, patch: AppPatch): Promise<AppItem> {
  if (inTauri()) {
    return invokeCore<AppItem>('apps_update', { id, patch })
  }
  try {
    return await request<AppItem>(`/api/v1/apps/${id}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    })
  } catch {
    return updateLocal(id, patch)
  }
}

export async function remove(id: number): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('apps_delete', { id })
    return
  }
  try {
    await request<unknown>(`/api/v1/apps/${id}`, { method: 'DELETE' })
  } catch {
    writeLocal(readLocal().filter((a) => a.id !== id))
  }
}

// ---------------------------------------------------------------- 原生能力

export async function launch(id: number): Promise<LaunchResult> {
  if (inTauri()) {
    return invokeCore<LaunchResult>('apps_launch', { id })
  }
  try {
    return await request<LaunchResult>(`/api/v1/apps/${id}/launch`, { method: 'POST' })
  } catch (err) {
    throw new NativeOnlyError('启动软件')
  }
}

/** 运行中的软件：`appId → pid`。 */
export async function running(): Promise<Record<string, number>> {
  if (inTauri()) {
    try {
      return await invokeCore<Record<string, number>>('apps_running')
    } catch {
      return {}
    }
  }
  try {
    return await request<Record<string, number>>('/api/v1/apps/running')
  } catch {
    return {}
  }
}

export async function pickFile(): Promise<string | null> {
  if (!inTauri()) {
    throw new NativeOnlyError('选择文件')
  }
  const res = await invokeCore<{ path: string | null }>('apps_pick_file')
  return res?.path ?? null
}

export async function probe(path: string): Promise<{ name: string; iconPath: string | null }> {
  if (!inTauri()) {
    throw new NativeOnlyError('自动补全（图标/名称探测）')
  }
  return invokeCore<{ name: string; iconPath: string | null }>('apps_probe', { path })
}

export async function scan(): Promise<InstalledApp[]> {
  if (!inTauri()) {
    throw new NativeOnlyError('扫描已安装软件')
  }
  const res = await invokeCore<{ items: InstalledApp[]; count: number }>('apps_scan')
  return res?.items ?? []
}

/** 读图标缓存 → data URL。webview 不能直接加载本地路径，必须经 core 读出来转 base64。 */
export async function iconData(path: string): Promise<string> {
  if (!path) throw new Error('icon path 为空')
  if (inTauri()) {
    return invokeCore<string>('apps_icon_data', { path })
  }
  try {
    return await request<string>(`/api/v1/icon?path=${encodeURIComponent(path)}`)
  } catch {
    throw new NativeOnlyError('加载图标')
  }
}

// ---------------------------------------------------------------- localStorage 降级

function readLocal(): AppItem[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as AppItem[]) : []
  } catch {
    return []
  }
}

function writeLocal(items: AppItem[]): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(items))
  } catch (err) {
    logger.warn('apps', `localStorage 写入失败：${String(err)}`)
  }
}

function filterLocal(items: AppItem[], category?: string, search?: string): AppItem[] {
  let out = items.slice()
  if (category) out = out.filter((a) => a.category === category)
  if (search) {
    const kw = search.trim().toLowerCase()
    out = out.filter(
      (a) => a.name.toLowerCase().includes(kw) || a.path.toLowerCase().includes(kw),
    )
  }
  // 与 core 的排序保持一致，避免"浏览器里看到的顺序和桌面端不一样"
  return out.sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) ||
      b.launch_count - a.launch_count ||
      a.name.localeCompare(b.name),
  )
}

function addLocal(input: AppInput): AppItem {
  const items = readLocal()
  if (items.some((a) => a.path === input.path)) {
    throw new Error(`该路径已在软件库中：${input.name}`)
  }
  const now = new Date().toISOString().slice(0, 19).replace('T', ' ')
  const item: AppItem = {
    id: (items.reduce((m, a) => Math.max(m, a.id), 0) || 0) + 1,
    name: input.name,
    path: input.path,
    args: input.args ?? '',
    icon: input.icon ?? null,
    type: input.type ?? null,
    category: input.category ?? null,
    launch_count: 0,
    last_used_at: null,
    pinned: false,
    created_at: now,
    updated_at: now,
  }
  writeLocal([...items, item])
  return item
}

function updateLocal(id: number, patch: AppPatch): AppItem {
  const items = readLocal()
  const idx = items.findIndex((a) => a.id === id)
  if (idx < 0) throw new Error(`软件不存在：id=${id}`)
  const merged: AppItem = { ...items[idx], ...patch } as AppItem
  items[idx] = merged
  writeLocal(items)
  return merged
}

export const appsApi = {
  list,
  categories,
  add,
  update,
  remove,
  launch,
  running,
  pickFile,
  probe,
  scan,
  iconData,
}
