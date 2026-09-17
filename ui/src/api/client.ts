/**
 * core 通信客户端。
 *
 * **主路径：Tauri invoke 通道**（不经 HTTP，不受 core 随机端口影响）。
 * 浏览器直开（vite dev，无 Tauri 容器）时降级到 HTTP（VITE_CORE_BASE）。
 *
 * 为什么主路径是 invoke（REVIEW-002 R-02 根因）：
 * core 的 HTTP 服务绑定**随机端口**并写入 `config(runtime.http_port)`；
 * 但红线 V7 禁止 UI 直接读 SQLite，UI 无从得知该端口；写死固定端口又与
 * 04 §5「不要用固定端口」冲突。Tauri command 通道绕开了端口本身 ——
 * 与 `/api/v1` 等价（契约 3.4 允许双通道），故以此为准。
 *
 * ⚠️ HTTP 通道的适用范围（实测边界，勿误解）：
 * core 的内部 HTTP API **不发送 CORS 头**（有意为之 —— 否则用户浏览器里
 * 任意网页都能读写本机数据）。因此：
 *   - 非浏览器客户端（curl / Python sidecar / 自动化脚本）：HTTP 通道可用；
 *   - **浏览器页面**（vite dev 直开）：跨源 fetch 会被浏览器拦下，
 *     实际生效的是 configService 的 **localStorage 降级**，而非 HTTP。
 * UI 在浏览器里"能跑"靠的是降级层，不是 HTTP 通道 —— 二者别混淆。
 */

import { invoke } from '@tauri-apps/api/core'
import { reactive } from 'vue'

import { logger } from '@/utils/logger'

export const connection = reactive({
  online: false,
  lastCheckedAt: 0,
})

/** 浏览器调试用的 HTTP 兜底地址（仅在非 Tauri 环境生效）。 */
export const API_BASE: string =
  (import.meta.env.VITE_CORE_BASE as string | undefined) ?? 'http://127.0.0.1:7520'

/** 是否运行在 Tauri WebView 内（决定走 invoke 还是 HTTP）。 */
export function inTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export function markOnline(): void {
  connection.online = true
  connection.lastCheckedAt = Date.now()
}

export function markOffline(): void {
  connection.online = false
}

/** 经 invoke 调 core 的 Tauri command（主路径）。 */
export async function invokeCore<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  try {
    const data = await invoke<T>(cmd, args)
    markOnline()
    return data
  } catch (err) {
    logger.error('core', `invoke ${cmd} 失败：${String(err)}`)
    throw err
  }
}

export interface ApiEnvelope<T> {
  ok: boolean
  data?: T
  error?: { code: string; message: string }
}

export class ApiError extends Error {
  readonly code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

/** HTTP 兜底通道（仅浏览器调试用）。 */
export async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 5000,
): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      signal: ctrl.signal,
    })
    const envelope = (await resp.json()) as ApiEnvelope<T>
    if (!envelope.ok || envelope.data === undefined) {
      throw new ApiError(
        envelope.error?.code ?? 'unknown',
        envelope.error?.message ?? 'unknown',
      )
    }
    markOnline()
    return envelope.data
  } catch (err) {
    logger.warn('core', `HTTP ${path} 失败：${String(err)}`)
    throw err
  } finally {
    clearTimeout(timer)
  }
}

/** 探活：Tauri 环境用 `ping` command，浏览器环境用 `/health`。 */
export async function checkConnection(): Promise<void> {
  if (inTauri()) {
    try {
      await invokeCore<string>('ping')
      return
    } catch {
      markOffline()
    }
  }
  try {
    await request<unknown>('/health', undefined, 1500)
  } catch {
    markOffline()
  }
}
