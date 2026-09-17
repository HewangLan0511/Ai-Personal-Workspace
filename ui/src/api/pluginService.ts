/**
 * 插件系统 / 外部 Agent / 桌面小组件 API 封装（阶段9 · 12 §A/§B/§C）。
 *
 * 通道约定与 deviceService 一致：Tauri invoke 为主，HTTP `/api/v1/*` 为备用。
 * 注意 AI 能力不经 HTTP（阶段5 订正），插件的 ai.invoke 在 pluginHost 里走 command。
 */

import { inTauri, invokeCore, request } from './client'

export interface PluginPerm {
  permission: string
  scope: string
}

export interface PluginRow {
  pluginId: string
  name: string
  version: string
  author: string
  description: string
  entry: string
  enabled: boolean
  installedAt: string
  permissions: PluginPerm[]
  ui?: { type: string; size: string; route: string } | null
}

export interface DiscoveredPlugin {
  pluginId: string
  dir: string
  manifest: Record<string, unknown>
}

export interface AuditRow {
  id: number
  pluginId: string
  action: string
  outcome: string
  detail: string
  createdAt: string
}

export interface AgentSpec {
  name: string
  url: string
  transport: string
  permissions: string[]
  healthCheck: string
  timeoutMs: number
}

export interface WidgetStatus {
  enabled: boolean
  open: boolean
  bounds: { x: number; y: number; w: number; h: number }
  alwaysOnTop: boolean
}

// ---- 插件（12 §A）----

export async function pluginsList(): Promise<PluginRow[]> {
  if (inTauri()) return invokeCore<PluginRow[]>('plugins_list')
  return request<PluginRow[]>('/api/v1/plugins')
}

export async function pluginsDiscover(): Promise<DiscoveredPlugin[]> {
  if (inTauri()) return invokeCore<DiscoveredPlugin[]>('plugins_discover')
  return request<DiscoveredPlugin[]>('/api/v1/plugins/discover')
}

/** core install 返回 {installed, plugin} 包裹；这里解包出 plugin 行。 */
interface InstallResp {
  installed: boolean
  plugin: PluginRow
}

export async function pluginsInstall(sourceDir: string): Promise<PluginRow> {
  if (inTauri()) {
    const r = await invokeCore<InstallResp>('plugins_install', { sourceDir })
    return r.plugin
  }
  const r = await request<InstallResp>('/api/v1/plugins/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sourceDir }),
  })
  return r.plugin
}

export async function pluginsImportZip(zipPath: string): Promise<PluginRow> {
  if (inTauri()) {
    const r = await invokeCore<InstallResp>('plugins_import_zip', { zipPath })
    return r.plugin
  }
  const r = await request<InstallResp>('/api/v1/plugins/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ zipPath }),
  })
  return r.plugin
}

export async function pluginsSetEnabled(pluginId: string, enabled: boolean): Promise<void> {
  if (inTauri()) {
    await invokeCore('plugins_set_enabled', { pluginId, enabled })
    return
  }
  await request('/api/v1/plugins/enabled', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pluginId, enabled }),
  })
}

/** 卸载。⚠️ 破坏性操作（红线 V5）——UI 层必须先弹二次确认。 */
export async function pluginsUninstall(pluginId: string): Promise<void> {
  if (inTauri()) {
    await invokeCore('plugins_uninstall', { pluginId })
    return
  }
  await request('/api/v1/plugins/uninstall', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pluginId }),
  })
}

/** 插件能力网关（UI 宿主桥用；每次调用 core 都会审计）。 */
export async function pluginApi(
  pluginId: string,
  api: string,
  method: string,
  payload: unknown = {},
): Promise<unknown> {
  if (inTauri()) {
    return invokeCore('plugin_api', { pluginId, api, method, payload: payload ?? {} })
  }
  return request('/api/v1/plugin/api', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pluginId, api, method, payload: payload ?? {} }),
  })
}

export async function pluginCrash(pluginId: string, reason: string): Promise<void> {
  if (inTauri()) {
    await invokeCore('plugin_crash', { pluginId, reason })
    return
  }
  await request('/api/v1/plugin/crash', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pluginId, reason }),
  })
}

export async function pluginAudit(pluginId: string, limit = 50): Promise<AuditRow[]> {
  if (inTauri()) {
    return invokeCore<AuditRow[]>('plugin_audit_list', { pluginId, limit })
  }
  const rows = await request<AuditRow[]>(
    `/api/v1/plugin/audit?pluginId=${encodeURIComponent(pluginId)}&limit=${limit}`,
  )
  return rows
}

// ---- 外部 Agent（12 §C）----

export async function agentsList(): Promise<AgentSpec[]> {
  if (inTauri()) return invokeCore<AgentSpec[]>('agents_list')
  return request<AgentSpec[]>('/api/v1/agents')
}

export async function agentsSave(specs: AgentSpec[]): Promise<{ saved: boolean; count: number }> {
  if (inTauri()) return invokeCore('agents_save', { specs })
  return request('/api/v1/agents', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(specs),
  })
}

export async function agentHealth(name: string): Promise<{ healthy: boolean; url: string }> {
  if (inTauri()) return invokeCore('agent_health', { name })
  return request('/api/v1/agent/health', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function agentInvoke(
  name: string,
  action: string,
  payload: unknown = {},
): Promise<unknown> {
  if (inTauri()) return invokeCore('agent_invoke', { name, action, payload })
  return request('/api/v1/agent/invoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, action, payload }),
  })
}

// ---- 桌面小组件（12 §B）----

export async function widgetStatus(): Promise<WidgetStatus> {
  if (inTauri()) return invokeCore<WidgetStatus>('desktop_widget_status')
  return request<WidgetStatus>('/api/v1/desktop-widget/status')
}

export async function widgetToggle(): Promise<{ open: boolean }> {
  if (inTauri()) return invokeCore('desktop_widget_toggle')
  return request('/api/v1/desktop-widget/toggle', { method: 'POST' })
}

export async function widgetSaveBounds(
  x: number,
  y: number,
  w: number,
  h: number,
): Promise<void> {
  if (inTauri()) {
    await invokeCore('desktop_widget_save_bounds', { x, y, w, h })
    return
  }
  await request('/api/v1/desktop-widget/bounds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, y, w, h }),
  })
}

export async function widgetSetAlwaysOnTop(on: boolean): Promise<void> {
  if (inTauri()) {
    await invokeCore('desktop_widget_set_always_on_top', { on })
    return
  }
  await request('/api/v1/desktop-widget/always-on-top', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on }),
  })
}

export const pluginApiEndpoints = {
  pluginsList,
  pluginsDiscover,
  pluginsInstall,
  pluginsImportZip,
  pluginsSetEnabled,
  pluginsUninstall,
  pluginApi,
  pluginCrash,
  pluginAudit,
  agentsList,
  agentsSave,
  agentHealth,
  agentInvoke,
  widgetStatus,
  widgetToggle,
  widgetSaveBounds,
  widgetSetAlwaysOnTop,
}
