/**
 * 配置服务封装。
 *
 * 三级通道（自高优先级到底）：
 *   1. Tauri invoke（`get_config` / `put_config`）—— 主路径，不受随机端口影响；
 *   2. HTTP `/api/v1/config/{key}` —— 仅浏览器直开调试时生效；
 *   3. localStorage —— 局部降级（02 §2.7：局部失败不拖垮整体）。
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

export const configApi = { get, put }
