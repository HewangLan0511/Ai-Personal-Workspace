/**
 * 配置服务封装。
 *
 * 三级通道（自高优先级到底）：
 *   1. Tauri invoke（`get_config` / `put_config`）—— 主路径，不受随机端口影响；
 *   2. HTTP `/api/v1/config/{key}` —— 仅供**非浏览器**客户端（curl / 脚本）；
 *   3. localStorage —— 浏览器直开（vite dev）时的真实降级通道（02 §2.7：局部失败不拖垮整体）。
 *
 * ⚠️ 实测边界：core 内部 HTTP API 不发 CORS 头（有意为之），浏览器页面跨源 fetch
 * 会被拦下 —— 所以在 vite dev 里跑，第 2 级实际不生效，落到第 3 级 localStorage。
 * 详见 `client.ts` 顶部注释。
 *
 * 降级语义：core 不可用时 UI 仍可读写（写入落本地），TopBar 会亮「降级模式」提示；
 * 对账（core 恢复后把本地变更回写 SQLite）属阶段2 规划，本阶段不做。
 */

import { inTauri, invokeCore, request } from './client'
import { logger } from '@/utils/logger'

const LS_PREFIX = 'pw.config.'

export async function get<T>(key: string, fallback: T): Promise<T> {
  if (inTauri()) {
    try {
      const raw = await invokeCore<unknown>('get_config', { key })
      return coerce<T>(raw, fallback)
    } catch (err) {
      logger.warn('config', `invoke get_config 失败，降级 HTTP：${String(err)}`)
    }
  }
  try {
    const raw = await request<unknown>(`/api/v1/config/${encodeURIComponent(key)}`)
    return coerce<T>(raw, fallback)
  } catch {
    logger.warn('config', `读取失败，降级 localStorage：${key}`)
    return readLocal<T>(key, fallback)
  }
}

export async function put<T>(key: string, value: T): Promise<void> {
  if (inTauri()) {
    try {
      await invokeCore<unknown>('put_config', { key, value })
      return
    } catch (err) {
      // 未登记键 / 类型不符会走到这里（core 侧校验拒绝）——属真实错误，需可见。
      logger.error('config', `invoke put_config 被拒：${key} → ${String(err)}`)
      throw err
    }
  }
  try {
    await request<unknown>(`/api/v1/config/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify(value),
    })
  } catch (err) {
    logger.warn('config', `HTTP 写入失败，降级 localStorage：${key}`)
    writeLocal(key, value)
  }
}

function readLocal<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key)
    if (raw === null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function writeLocal<T>(key: string, value: T): void {
  try {
    localStorage.setItem(LS_PREFIX + key, JSON.stringify(value))
  } catch (err) {
    // localStorage 满了或禁用，丢弃；下次启动取默认值（体验维可接受）
    logger.warn('config', `localStorage 写入失败：${String(err)}`)
  }
}

function coerce<T>(raw: unknown, fallback: T): T {
  return raw === null || raw === undefined ? fallback : (raw as T)
}

/**
 * **严格读**（C4：Workspace Snapshot 持久化专用）。
 *
 * 与 `get()` 的区别：**不做 localStorage 降级**。C4-D2 明确禁止用 localStorage 替代
 * Core 持久化 —— 若把浏览器本地副本当成"快照已持久化"，验收会在重启后假绿。
 * 读不到就是读不到（抛错），由调用方决定 fail-closed。
 */
export async function getCore<T>(key: string): Promise<T | null> {
  if (inTauri()) {
    const raw = await invokeCore<unknown>('get_config', { key })
    return (raw ?? null) as T | null
  }
  return request<T>(`/api/v1/config/${encodeURIComponent(key)}`)
}

/**
 * **严格写**（C4：Workspace Snapshot 持久化专用）。
 *
 * 与 `put()` 的区别：失败**直接抛错**，绝不静默落到 localStorage ——
 * 「写成功」必须等于「Core config 已落库」。
 */
export async function putCore<T>(key: string, value: T): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('put_config', { key, value })
    return
  }
  await request<unknown>(`/api/v1/config/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify(value),
  })
}

export const configApi = { get, put, getCore, putCore }
