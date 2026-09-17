/**
 * 事件总线前端桥（**L-017 / L-032 修复**）。
 *
 * core 侧 `event_bus::bridge_to_webview` 把每个 Envelope 通过 Tauri event
 * `pw://event` 原样转发过来，本模块负责：
 *   1. 建立**唯一**的 Tauri event 监听（避免每个功能各 listen 一次）；
 *   2. 按 `envelope.event`（事件名）分发给注册的回调；
 *   3. 维护"最近事件"环形缓冲，供调试面板与验收脚本查询。
 *
 * 契约 3.3：Envelope = `{ event, ts, payload }`。
 *
 * ⚠️ 浏览器环境（vite dev 直开）没有 Tauri 容器，收不到事件 —— 此时本模块
 * 静默失效（不报错、不影响页面），与 client.ts 的降级策略一致。
 * 验收脚本若要在浏览器里验证事件，须走真实 Tauri 窗口或改验 core 侧 publish。
 */

import { listen } from '@tauri-apps/api/event'
import type { UnlistenFn } from '@tauri-apps/api/event'

import { inTauri } from '@/api/client'
import { logger } from '@/utils/logger'

/** 契约 3.3 统一事件信封。 */
export interface Envelope {
  event: string
  ts: string
  payload: Record<string, unknown>
}

type Handler = (envelope: Envelope) => void

/** 事件名 → 订阅者集合。 */
const handlers = new Map<string, Set<Handler>>()
/** 通配订阅者（`onAny`）：不关心事件名、只要全部流量的场景（如调试面板）。 */
const anyHandlers = new Set<Handler>()

/** 最近事件环形缓冲（容量固定，供调试与验收查询，不做无限增长）。 */
const RECENT_LIMIT = 200
const recent: Envelope[] = []

let unlisten: UnlistenFn | null = null
let started = false

/** 收到事件后的内部分发（导出仅为单测/验收使用）。 */
export function dispatch(envelope: Envelope): void {
  recent.push(envelope)
  if (recent.length > RECENT_LIMIT) recent.shift()

  const set = handlers.get(envelope.event)
  if (set) {
    for (const fn of set) {
      try {
        fn(envelope)
      } catch (e) {
        // 单个订阅者抛错不得影响其他订阅者（事件分发要隔离故障）
        logger.error('event', `${envelope.event} 订阅者异常：${String(e)}`)
      }
    }
  }
  for (const fn of anyHandlers) {
    try {
      fn(envelope)
    } catch (e) {
      logger.error('event', `onAny 订阅者异常：${String(e)}`)
    }
  }
}

/** 启动桥（幂等）。应在 App 挂载时调用一次。 */
export async function startEventBridge(): Promise<void> {
  if (started || !inTauri()) return
  started = true
  try {
    unlisten = await listen<Envelope>('pw://event', (e) => {
      if (e.payload) dispatch(e.payload)
    })
  } catch (e) {
    // 桥启动失败不应让应用崩 —— 只是收不到实时事件（轮询兜底仍在）
    started = false
    logger.warn('event', `事件桥启动失败：${String(e)}`)
  }
}

/** 停止桥（应用卸载时调用）。 */
export function stopEventBridge(): void {
  unlisten?.()
  unlisten = null
  started = false
}

/** 订阅指定事件名，返回取消函数。 */
export function on(event: string, fn: Handler): () => void {
  let set = handlers.get(event)
  if (!set) {
    set = new Set()
    handlers.set(event, set)
  }
  set.add(fn)
  return () => set?.delete(fn)
}

/** 订阅全部事件（调试用），返回取消函数。 */
export function onAny(fn: Handler): () => void {
  anyHandlers.add(fn)
  return () => anyHandlers.delete(fn)
}

/** 最近收到的事件快照（验收脚本 / 调试面板用）。 */
export function recentEvents(): readonly Envelope[] {
  return recent
}

/** 桥是否已建立（供状态栏/诊断显示）。 */
export function bridgeActive(): boolean {
  return started
}
