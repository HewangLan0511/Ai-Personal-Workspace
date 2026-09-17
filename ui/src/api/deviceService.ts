/**
 * 设备中心 API 封装（阶段8 · `11-阶段指令-生活与设备.md` §B）。
 *
 * 通道：Tauri invoke 为主，HTTP `/api/v1/device/*` 为备用。
 * 指标历史是 core 内存环形缓冲（不落库）；进程 CPU% 为跨请求差分。
 */

import { inTauri, invokeCore, request } from './client'

export interface MetricsPoint {
  ts: number
  cpu: number
  mem_used: number
  mem_total: number
  disks: { letter: string; total_bytes: number; free_bytes: number }[]
}

export interface MetricsSnapshot {
  current: MetricsPoint
  history: MetricsPoint[]
}

export interface ProcInfo {
  pid: number
  name: string
  mem_bytes: number
  cpu_percent: number
}

export interface ModeHealth {
  modes: {
    modeId: number
    modeName: string
    apps: { name: string; launchCount: number; usedSecondsToday: number }[]
  }[]
}

export async function metrics(): Promise<MetricsSnapshot> {
  if (inTauri()) return invokeCore<MetricsSnapshot>('device_metrics')
  return request<MetricsSnapshot>('/api/v1/device/metrics')
}

export async function processes(): Promise<ProcInfo[]> {
  if (inTauri()) {
    const r = await invokeCore<{ processes: ProcInfo[] }>('device_processes')
    return r.processes
  }
  const r = await request<{ processes: ProcInfo[] }>('/api/v1/device/processes')
  return r.processes
}

/** 结束进程。⚠️ confirm 必须 true（红线 V5：破坏性操作）——UI 层必须先弹二次确认。 */
export async function killProcess(pid: number): Promise<void> {
  if (inTauri()) {
    await invokeCore('device_process_kill', { pid, confirm: true })
    return
  }
  await request('/api/v1/device/processes/kill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pid, confirm: true }),
  })
}

export async function modeHealth(): Promise<ModeHealth> {
  if (inTauri()) return invokeCore<ModeHealth>('device_mode_health')
  return request<ModeHealth>('/api/v1/device/mode-health')
}

/** 聚合出口（与 profileApi 同风格，视图统一从这里取）。 */
export const deviceApi = {
  metrics,
  processes,
  killProcess,
  modeHealth,
}
