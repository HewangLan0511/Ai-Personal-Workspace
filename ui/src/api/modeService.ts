/**
 * 工作模式 API 封装（阶段4 / 06-阶段指令-工作模式引擎 ★）。
 *
 * 通道：Tauri invoke 为主，HTTP `/api/v1/*` 为备用（非浏览器客户端）。
 * 浏览器预览下：**读取类**可用（列表/详情），**应用/取消**会明确抛错（没有窗口与进程能力）。
 */

import { inTauri, invokeCore, request } from './client'

export interface OpenTarget {
  path: string
  label?: string | null
  type?: string | null
}

export interface AiProfile {
  provider: string
  systemPromptKey: string
  permissionScope: string[]
}

export interface WorkMode {
  id: number
  name: string
  description: string | null
  icon: string | null
  apps: string[]
  openTargets: OpenTarget[]
  layout: string | null
  aiProfile: AiProfile | null
  autoApply: boolean
  switchPolicy: string
  useCount: number
  lastUsedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface WorkModeInput {
  name: string
  description?: string | null
  icon?: string | null
  apps?: string[]
  openTargets?: OpenTarget[]
  layout?: string | null
  aiProfile?: AiProfile | null
  autoApply?: boolean
  switchPolicy?: string
}

export class NativeOnlyError extends Error {
  constructor(action: string) {
    super(`「${action}」需要桌面端运行（浏览器预览没有进程与窗口能力）`)
    this.name = 'NativeOnlyError'
  }
}

/** 单项执行结果（06 §2「可重试」依据 `retriable`）。 */
export interface SlotResult {
  app: string
  appId: number | null
  status:
    | 'launched'
    | 'already_running'
    | 'failed'
    | 'skipped_cancelled'
    | string
  pid: number | null
  reason: string | null
  retriable: boolean
}

export interface ApplyStateDto {
  phase: string
  done?: number
  total?: number
  ready?: number
  failed?: number
  reason?: string
}

export interface ApplyOutcome {
  modeId: number
  modeName: string
  state: ApplyStateDto
  launched: number
  alreadyRunning: number
  failed: number
  arranged: number
  filesOpened: number
  slots: SlotResult[]
  tookMs: number
  cancelled: boolean
  arrangeNote: string | null
  /** `exclusive` 下被关闭的软件（只含上一个模式拉起的） */
  closed: string[]
  policy: string
  /** 06 §3 `ask`：需要 UI 询问用户 */
  askPending: boolean
}

export interface ModeCurrent {
  configured: unknown
  running: string | null
  launchedAppIds: number[]
  previous?: string | null
  lastSnapshot?: [string, number[]] | null
}

export interface ProgressInfo {
  active: boolean
  modeId?: number
  modeName?: string
  state: ApplyStateDto
  slots: SlotResult[]
}

export interface LayoutRecord {
  id: number
  name: string
  description: string | null
  slots: unknown
  monitor: number
  isBuiltin: boolean
}

// ---------------------------------------------------------------- 模式 CRUD

export async function list(): Promise<WorkMode[]> {
  if (inTauri()) return invokeCore<WorkMode[]>('modes_list')
  return request<WorkMode[]>('/api/v1/modes')
}

export async function get(id: number): Promise<WorkMode | null> {
  if (inTauri()) return invokeCore<WorkMode | null>('modes_get', { id })
  return request<WorkMode | null>(`/api/v1/modes/${id}`)
}

export async function add(input: WorkModeInput): Promise<WorkMode> {
  if (inTauri()) return invokeCore<WorkMode>('modes_add', { input })
  return request<WorkMode>('/api/v1/modes', { method: 'POST', body: JSON.stringify(input) })
}

/** 「从当前工作环境创建模式」：用户只给名字，系统识别应用与布局（2026-09-13 交互重构）。 */
/** 「从当前工作环境创建模式」：用户只给名字，系统识别应用与布局（2026-09-13 交互重构）。 */
export async function captureCurrent(
  name: string,
): Promise<{ mode: WorkMode; layout: string; captured: string[] }> {
  if (inTauri()) return invokeCore('modes_capture_current', { name })
  return request('/api/v1/mode/capture', { method: 'POST', body: JSON.stringify({ name }) })
}

export async function update(id: number, patch: Partial<WorkModeInput>): Promise<WorkMode> {
  if (inTauri()) return invokeCore<WorkMode>('modes_update', { id, patch })
  return request<WorkMode>(`/api/v1/modes/${id}`, { method: 'PUT', body: JSON.stringify(patch) })
}

export async function remove(id: number): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('modes_delete', { id })
    return
  }
  await request<unknown>(`/api/v1/modes/${id}`, { method: 'DELETE' })
}

export async function duplicate(id: number): Promise<WorkMode> {
  if (inTauri()) return invokeCore<WorkMode>('modes_duplicate', { id })
  return request<WorkMode>(`/api/v1/modes/${id}/duplicate`, { method: 'POST' })
}

// ---------------------------------------------------------------- 应用 / 状态

export async function current(): Promise<ModeCurrent> {
  if (inTauri()) return invokeCore<ModeCurrent>('modes_current')
  return request<ModeCurrent>('/api/v1/mode/current')
}

export async function apply(id: number, policy?: string): Promise<ApplyOutcome> {
  if (inTauri()) return invokeCore<ApplyOutcome>('mode_apply', { modeId: id, policy: policy ?? null })
  try {
    return await request<ApplyOutcome>(`/api/v1/modes/${id}/apply`, { method: 'POST' })
  } catch {
    throw new NativeOnlyError('进入模式')
  }
}

export async function cancel(): Promise<{ cancelled: boolean; modeName?: string; reason?: string }> {
  if (inTauri()) return invokeCore('mode_cancel')
  return request('/api/v1/mode/cancel', { method: 'POST' })
}

export async function progress(): Promise<ProgressInfo> {
  if (inTauri()) return invokeCore<ProgressInfo>('mode_progress')
  return request<ProgressInfo>('/api/v1/mode/progress')
}

export async function restore(): Promise<ApplyOutcome> {
  if (inTauri()) return invokeCore<ApplyOutcome>('mode_restore')
  return request<ApplyOutcome>('/api/v1/mode/restore', { method: 'POST' })
}

/** 退出当前模式：关闭**该模式自己拉起的**软件（用户手动开的一个都不碰）。 */
export async function exit(): Promise<{ closed: string[] }> {
  if (inTauri()) return invokeCore<{ closed: string[] }>('mode_exit')
  return request<{ closed: string[] }>('/api/v1/mode/exit', { method: 'POST' })
}

/** 记住 06 §3 `ask` 策略的选择。 */
export async function rememberSwitch(from: string, to: string, policy: string): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('modes_remember_switch', { from, to, policy })
    return
  }
  await request<unknown>('/api/v1/mode/remember', {
    method: 'POST',
    body: JSON.stringify({ from, to, policy }),
  })
}

// ---------------------------------------------------------------- 布局（DB 为真相）

export async function dbLayouts(): Promise<LayoutRecord[]> {
  if (inTauri()) return invokeCore<LayoutRecord[]>('db_layouts_list')
  return request<LayoutRecord[]>('/api/v1/db/layouts')
}

export async function dbLayoutUpsert(
  name: string,
  description: string | null,
  slots: unknown,
  monitor = 0,
): Promise<LayoutRecord> {
  if (inTauri()) {
    return invokeCore<LayoutRecord>('db_layout_upsert', { name, description, slots, monitor })
  }
  return request<LayoutRecord>('/api/v1/db/layouts', {
    method: 'POST',
    body: JSON.stringify({ name, description, slots, monitor }),
  })
}

export const modeApi = {
  list,
  get,
  add,
  captureCurrent,
  update,
  remove,
  duplicate,
  current,
  apply,
  cancel,
  progress,
  restore,
  exit,
  rememberSwitch,
  dbLayouts,
  dbLayoutUpsert,
}
