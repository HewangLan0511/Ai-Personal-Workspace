/**
 * AI 助手应用层 —— 传输端口（TECH-05-D §P1-A）
 *
 * ## 它是"唯一入口"里最靠里的那一段
 * ```
 *   /ai 页面 · AI 侧栏
 *        │  ① 只调应用层语义入口（send / cancel / previewContext）
 *        ▼
 *   ai/assistant/service.ts  ── 解析目标（canonical 优先）+ 权限边界
 *        │  ② 只传已解析好的参数
 *        ▼
 *   本文件（AI Transport Port）   ← **全应用唯一出现 ai_chat / ai_cancel /
 *        │                           ai_preview_context 的地方**
 *        ▼
 *   core（Tauri command）→ sidecar /ai/chat → Provider
 * ```
 *
 * ## 为什么单独一个文件（而不是留在 store 里）
 * 冻结契约给 transport 的定语是 `role: "resolved-only"`、`mayDecide: false` ——
 * **传输层不许做决定**。此前 `stores/ai.ts::send()` 一边持状态、一边拼参数、
 * 一边调 invoke，三件事混在一处，"谁决定了用哪个模型"说不清。
 * 抽出来之后，本文件里**没有任何 if 在挑 provider**：给它什么发什么。
 *
 * ## 与模型域 `ports.ts` 的分工（刻意对称）
 * | 文件 | 管什么 | 碰的 command |
 * |------|--------|--------------|
 * | 模型域 `ports.ts` | **模型域**的 IO（有哪些 Provider/模型、canonical、凭据） | `ai_info` / `ai_list_models` / `get_config` / `put_config` / 凭据三条 |
 * | `ai/assistant/transport.ts`（本文件） | **一次对话**的传输（请求/中断/上下文预览） | `ai_chat` / `ai_cancel` / `ai_preview_context` |
 *
 * 两个域各自一个 IO 适配器，互不混用 —— 模型域不认识"对话"，对话域不认识"canonical 键"。
 *
 * ## 本轮没有新增任何 core 命令
 * 三个命令都**早已存在**（`core/src/api/commands.rs`），本文件只是把它们
 * 收进一个具名端口。改 `ai_chat` 的参数体仍然只需改 `request.ts::buildChatArgs`。
 */

import { inTauri, invokeCore } from '@/api/client'
import { on, type Envelope } from '@/api/eventBridge'
import { logger } from '@/utils/logger'

import type { AiMode } from './session'
import type { ChatArgs, ScopePrefs } from './request'

// ---------------------------------------------------------------- 返回结构（core 契约）

/** `ai_chat` 的返回值（流式内容走事件，此处只用于收尾）。 */
export interface ChatResult {
  text: string
  chunkCount: number
  durationMs: number
}

/** `ai_preview_context` 的返回值（"本次会带哪些上下文"）。 */
export interface ContextPreview {
  context: Record<string, unknown> | null
  usedScopes: string[]
}

/** 流式增量事件的载荷。 */
export interface StreamChunk {
  delta: string
}

// ---------------------------------------------------------------- 端口接口

/**
 * AI 传输端口。**语义只有三件事**，且都以"已经解析好的参数"为输入。
 *
 * 验收脚本用假实现替换它来驱动真实编排逻辑（不真发请求），
 * 因此 interface 里不允许出现任何"顺手解析一下默认值"的入口。
 */
export interface AiTransport {
  /** 发起一次对话。参数由 `request.ts::buildChatArgs` 装配，本层不再改。 */
  chat(args: ChatArgs): Promise<ChatResult>
  /** 请求中断当前生成。 */
  cancel(): Promise<void>
  /** 预览本次会带哪些上下文（用于 UI 标签与"权限提示"核对）。 */
  previewContext(mode: AiMode, scopePrefs: ScopePrefs): Promise<ContextPreview>
  /** 订阅流式增量。返回退订函数。 */
  onChunk(fn: (chunk: StreamChunk) => void): () => void
  /** 订阅"响应结束"。返回退订函数。 */
  onDone(fn: () => void): () => void
}

// ---------------------------------------------------------------- core 实现

/** 事件名（契约 3.3；与 core 侧 publish 的名字一致，**不得改**）。 */
export const EVENT_STREAM_CHUNK = 'AI_STREAM_CHUNK'
export const EVENT_RESPONSE = 'AI_RESPONSE'

/**
 * 生产实现：Tauri command 通道。
 *
 * 三处如实降级（**不假装成功**）：
 * - 非 Tauri 环境（浏览器）没有 core：`chat` 直接抛，由上层转成可读错误；
 * - 事件通道在浏览器里收不到：`chat` 的返回值仍会兜底填充完整文本（见 session.settleReply）；
 * - `cancel` 失败不影响本地状态复位（取消失败不该把 UI 卡在 loading）。
 */
export function coreAiTransport(): AiTransport {
  return {
    async chat(args: ChatArgs): Promise<ChatResult> {
      if (!inTauri()) {
        // 明确失败：浏览器直开时没有 core，别让 UI 停在"正在生成…"
        throw new Error('sidecar 尚未就绪（当前环境没有核心服务）')
      }
      return invokeCore<ChatResult>('ai_chat', { args })
    },

    async cancel(): Promise<void> {
      if (!inTauri()) return
      try {
        await invokeCore('ai_cancel')
      } catch {
        /* 取消失败不影响本地状态复位 */
      }
    },

    async previewContext(mode: AiMode, scopePrefs: ScopePrefs): Promise<ContextPreview> {
      if (!inTauri()) return { context: null, usedScopes: [] }
      return invokeCore<ContextPreview>('ai_preview_context', {
        mode,
        enabledScopes: scopePrefs,
      })
    },

    onChunk(fn: (chunk: StreamChunk) => void): () => void {
      // 事件桥在非 Tauri 环境静默失效 —— 这里同样静默（不注册即不消耗）
      if (!inTauri()) return () => undefined
      return on(EVENT_STREAM_CHUNK, (env: Envelope) => {
        const delta = String((env.payload as Record<string, unknown>)?.delta ?? '')
        if (delta) fn({ delta })
      })
    },

    onDone(fn: () => void): () => void {
      if (!inTauri()) return () => undefined
      return on(EVENT_RESPONSE, () => fn())
    },
  }
}

/**
 * 内存实现（验收/单测用）：**只记录被调用的参数，不产生网络 IO**。
 *
 * 存在的意义是让验收脚本能回答"这一次请求到底带了什么"：
 * 权限边界的断言（咨询模式不得出现 project/profile）读的就是 `calls`。
 */
export interface MemoryTransport extends AiTransport {
  /** 依次收到的请求参数（验收断言用）。 */
  readonly calls: ChatArgs[]
  /** 依次收到的 `previewContext` 入参。 */
  readonly previews: Array<{ mode: AiMode; scopePrefs: ScopePrefs }>;
  /** 注入返回文本（默认回显 provider/model，便于断言"发给了谁"）。 */
  reply: string | null
  /** 注入错误（非空则 `chat` 抛错，用于验证 error 状态）。 */
  failWith: string
  /** 手动把一段增量推给订阅者（模拟流式）。 */
  pushChunk(delta: string): void
  /** 手动触发"响应结束"。 */
  pushDone(): void
}

export function memoryTransport(): MemoryTransport {
  const calls: ChatArgs[] = []
  const previews: Array<{ mode: AiMode; scopePrefs: ScopePrefs }> = []
  const chunkFns = new Set<(c: StreamChunk) => void>()
  const doneFns = new Set<() => void>()
  const state = { reply: null as string | null, failWith: '' }

  return {
    calls,
    previews,
    get reply() {
      return state.reply
    },
    set reply(v: string | null) {
      state.reply = v
    },
    get failWith() {
      return state.failWith
    },
    set failWith(v: string) {
      state.failWith = v
    },
    async chat(args: ChatArgs): Promise<ChatResult> {
      calls.push(args)
      if (state.failWith) throw new Error(state.failWith)
      if (state.reply === null) {
        return { text: '', chunkCount: 0, durationMs: 0 }
      }
      return { text: state.reply, chunkCount: 1, durationMs: 1 }
    },
    async cancel(): Promise<void> {
      /* 内存实现无需中断 */
    },
    async previewContext(mode: AiMode, scopePrefs: ScopePrefs): Promise<ContextPreview> {
      previews.push({ mode, scopePrefs })
      if (mode !== 'workspace') return { context: null, usedScopes: [] }
      const used = (Object.keys(scopePrefs) as Array<keyof ScopePrefs>).filter(
        (k) => scopePrefs[k],
      )
      return { context: {}, usedScopes: used as string[] }
    },
    onChunk(fn) {
      chunkFns.add(fn)
      return () => chunkFns.delete(fn)
    },
    onDone(fn) {
      doneFns.add(fn)
      return () => doneFns.delete(fn)
    },
    pushChunk(delta: string) {
      for (const fn of chunkFns) fn({ delta })
    },
    pushDone() {
      for (const fn of doneFns) fn()
    },
  }
}

/** 把 core / sidecar 的错误码转成用户能读懂的话（08 §7）。 */
export function humanizeAiError(raw: string): string {
  const map: Array<[RegExp, string]> = [
    [/no_api_key/, '尚未配置 API Key —— 请到「设置 → AI」中添加'],
    [/local_model_down/, '本地模型未运行 —— 请先启动 Ollama / LM Studio'],
    [/unreachable/, '网络不可达 —— 可切换到本地模型继续使用'],
    [/timeout/, '请求超时 —— 可重试或换用更快的模型'],
    [/rate_limit/, '请求过于频繁 —— 请稍后再试'],
    [/auth_failed/, 'API Key 被拒绝 —— 请检查密钥是否正确'],
    [/not_implemented/, '该 Provider 尚未开放'],
    [/尚未选择模型/, '尚未选择模型 —— 请到「模型管理」中选择'],
    [/sidecar 尚未就绪/, '核心服务仍在启动中，请稍候重试'],
  ]
  for (const [re, msg] of map) {
    if (re.test(raw)) return msg
  }
  return raw
}

/** 统一记一笔失败日志（调用方不需要知道 logger 的存在）。 */
export function logTransportFailure(where: string, e: unknown): void {
  logger.warn('ai-assistant', `${where} 失败：${String(e)}`)
}
