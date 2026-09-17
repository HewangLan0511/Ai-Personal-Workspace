/**
 * Core 运行时身份事实（TECH-07-C4）。
 *
 * 用途只有一个：给 Workspace Snapshot v1 的 `source`（appVersion / corePid / runId）
 * 提供**真实出口**。C4 之前 core 没有任何进程身份出口（`/health` 只有 `service`，
 * Tauri 主路径又不经过 HTTP），因此：
 *   - Tauri：`ping` 命令（既有探活口，C4 起返回同形身份 JSON 字符串，非新命令）；
 *   - 浏览器/脚本：HTTP `/health`。
 * 两条路都只是**读取 core 自报的事实**，本文件不做任何加工/缓存/兜底。
 */

import { inTauri, invokeCore, request } from './client'

/** core 实例身份（`/health` 与 `ping` 同形）。 */
export interface CoreIdentity {
  service: string
  /** core 进程真实 pid。 */
  pid: number
  /** core 本次实例真实启动时刻（epoch ms）。 */
  started_at: number
}

function isIdentity(v: unknown): v is CoreIdentity {
  if (typeof v !== 'object' || v === null) return false
  const o = v as Record<string, unknown>
  return (
    typeof o.pid === 'number' &&
    Number.isInteger(o.pid) &&
    o.pid > 0 &&
    typeof o.started_at === 'number' &&
    Number.isFinite(o.started_at) &&
    o.started_at > 0
  )
}

/**
 * 读取 core 身份事实。拿不到/形态不对时返回 `null` —— **绝不编造**
 * （Snapshot 的 `source` 必须来自 core 真实事实）。
 */
export async function coreIdentity(): Promise<CoreIdentity | null> {
  if (inTauri()) {
    try {
      const raw = await invokeCore<string>('ping')
      const parsed: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      return isIdentity(parsed) ? parsed : null
    } catch {
      return null
    }
  }
  try {
    const v: unknown = await request<unknown>('/health', undefined, 3000)
    return isIdentity(v) ? v : null
  } catch {
    return null
  }
}

/**
 * 应用版本（Snapshot `source.appVersion`）。
 *
 * 由 vite `define` 注入（见 `vite.config.ts`，取自 package.json），
 * 避免在这里硬编码一份会漂移的副本。
 */
declare const __PW_APP_VERSION__: string | undefined

export function appVersion(): string {
  return typeof __PW_APP_VERSION__ === 'string' && __PW_APP_VERSION__
    ? __PW_APP_VERSION__
    : '0.0.0-unknown'
}

export const systemApi = { coreIdentity, appVersion }
