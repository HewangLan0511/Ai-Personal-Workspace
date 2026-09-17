/**
 * AI 助手应用层 —— 会话状态（TECH-05-D §P1-A）· **纯状态机，零 IO / 零框架**
 *
 * ## 它解决什么
 * TECH-05-D 审计结论：`/ai` 页面此前是一个 366 字节的占位骨架（只有三行文案），
 * 真正的对话只在右侧 AI 侧栏里发生，且会话状态是**隐式**的 ——
 * "正在生成 / 出错 / 空会话"全靠 store 里 `streaming` 与 `messages.length` 现算，
 * 没有一处能回答"这次会话现在处于什么状态"。
 *
 * 本文件把这件事显式化：**会话状态的唯一定义处**。
 *
 * ```
 *   会话状态（本文件，纯函数）
 *     unset   从未开会话
 *     empty   有会话但一条消息都没有
 *     idle    有历史消息、当前无请求
 *     loading 有一次请求在飞
 *     error   最近一次请求失败
 * ```
 *
 * ## 为什么是纯函数
 * 同模型域 `selection.ts` 的理由：纯函数可以被**枚举验证**。
 * 验收脚本把它编译成 JS 在 Node 里跑，穷举 (有会话?, 消息数, 在飞?, 有错?)
 * 的全部组合，断言状态归约结果 —— 而不是"读一遍代码觉得对"。
 *
 * ## 零依赖
 * 不 import Vue、不 import `@/`、不碰 IO。谁持有会话由调用方决定
 * （当前是 `stores/ai.ts`；本文件不关心）。
 */

/** 对话模式（契约 3.1：`ai_conversations.mode = consult | workspace`）。 */
export type AiMode = 'consult' | 'workspace'

/** 消息角色。 */
export type ChatRole = 'user' | 'assistant'

/** 一条消息。**没有 id 之外的隐式状态** —— 流式/错误都挂在消息自己身上。 */
export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  /** 流式中（显示光标、禁止重复发送）。 */
  streaming?: boolean
  /** 该条消息的失败信息（不弹全局窗，用户能看出"哪一次失败"）。 */
  error?: string
}

/** 一个会话（应用层状态；本轮**不落库**，见文件头说明）。 */
export interface AiSession {
  id: string
  mode: AiMode
  /** 会话标题（取首条用户消息；空会话时为占位文案）。 */
  title: string
  messages: ChatMessage[]
  /** 创建时间（ms）。 */
  createdAt: number
  /** 最近活动时间（ms）。 */
  updatedAt: number
}

/**
 * 会话状态枚举 —— **本层是这个名字的唯一权威**。
 * UI 只做映射（显示文案/图标），不得自己再定义一套。
 */
export const SESSION_STATUSES = ['unset', 'empty', 'idle', 'loading', 'error'] as const
export type SessionStatus = (typeof SESSION_STATUSES)[number]

/** 会话状态的**输入事实**（全部来自应用层，UI 不得自行拼装其它判据）。 */
export interface SessionFacts {
  /** 是否存在当前会话（`sessionId` 有值且能被选中）。 */
  hasSession: boolean
  /** 当前会话的消息条数。 */
  messageCount: number
  /** 是否有请求在飞。 */
  streaming: boolean
  /** 最近一次请求的错误（空串 = 无错）。 */
  lastError: string
}

/**
 * 归约会话状态。**判据优先级：unset > loading > error > empty > idle**。
 *
 * 顺序有讲究：
 * - `unset` 先于一切 —— 没有会话时"在飞/出错"都无意义（不可能发生，但归约要确定）；
 * - `loading` 先于 `error` —— 重试期间旧错误不该继续把状态钉在 error；
 * - `empty` 先于 `idle` —— "一条消息都没有"是新会话的初始态，不是"闲着的历史会话"。
 *
 * 纯函数：同输入同输出，不读任何全局。
 */
export function sessionStatusOf(f: SessionFacts): SessionStatus {
  if (!f.hasSession) return 'unset'
  if (f.streaming) return 'loading'
  if (f.lastError) return 'error'
  if (f.messageCount <= 0) return 'empty'
  return 'idle'
}

/** 会话状态 → 一句人话（进日志 / 状态栏 / 验收输出，不参与判断）。 */
export const SESSION_STATUS_LABEL: Record<SessionStatus, string> = {
  unset: '尚未开始会话',
  empty: '新会话，可以开始提问',
  idle: '就绪',
  loading: '正在生成…',
  error: '上次请求失败',
}

// ---------------------------------------------------------------- 会话构造与选择

let idSeq = 0

/**
 * 生成会话 id。
 *
 * **刻意不做 uuid**：会话本轮不落库，id 只需在进程内唯一。
 * 用时间戳 + 递增序号（不掺随机数）—— 同一毫秒内多次新建也能得到确定的不同 id，
 * 验收脚本因此可以稳定断言"新建会话 ⇒ id 变化"。
 */
export function newSessionId(now: number = Date.now()): string {
  idSeq += 1
  return `s${now.toString(36)}-${idSeq}`
}

/** 生成消息 id（同理由：进程内唯一即可）。 */
export function newMessageId(now: number = Date.now()): string {
  idSeq += 1
  return `m${now.toString(36)}-${idSeq}`
}

/** 空会话的占位标题。 */
export const UNTITLED_SESSION = '新会话'

/**
 * 从首条用户消息提炼会话标题（原型 UI：会话列表显示标题）。
 * 取第一行、截断到 20 字；没有用户消息时给占位文案。
 */
export function titleOf(messages: readonly ChatMessage[], fallback: string = UNTITLED_SESSION): string {
  const first = messages.find((m) => m.role === 'user' && m.content.trim())
  if (!first) return fallback
  const line = first.content.trim().split('\n')[0] ?? ''
  const text = line.trim()
  if (!text) return fallback
  return text.length > 20 ? `${text.slice(0, 20)}…` : text
}

/** 新建一个空会话。 */
export function createSession(mode: AiMode, now: number = Date.now()): AiSession {
  return {
    id: newSessionId(now),
    mode,
    title: UNTITLED_SESSION,
    messages: [],
    createdAt: now,
    updatedAt: now,
  }
}

/**
 * 按模式筛选会话（原型：聊天 / 工作空间助手 两套会话互不混）。
 * **纯：不改动入参，返回新数组**。
 */
export function sessionsOf(sessions: readonly AiSession[], mode: AiMode): AiSession[] {
  return sessions.filter((s) => s.mode === mode)
}

/**
 * 选出"当前会话"：优先 `sessionId`；否则取该模式下最近活动的一个；都没有则 `null`。
 *
 * 这一步是显式的 —— 此前"当前会话是谁"散落在组件里，容易出现
 * "列表高亮 A、聊天区渲染 B"这种不一致。
 */
export function currentSessionOf(
  sessions: readonly AiSession[],
  sessionId: string,
  mode: AiMode,
): AiSession | null {
  const scoped = sessionsOf(sessions, mode)
  if (!scoped.length) return null
  const hit = scoped.find((s) => s.id === sessionId)
  if (hit) return hit
  return scoped.reduce((a, b) => (b.updatedAt > a.updatedAt ? b : a))
}

// ---------------------------------------------------------------- 消息归约（纯）

/**
 * 取最后一条 assistant 消息的下标（没有则 -1）。
 * 流式片段要追加到"当前这条回复"上，索引必须由本层统一给出。
 */
export function lastAssistantIndex(messages: readonly ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === 'assistant') return i
  }
  return -1
}

/**
 * 把流式片段并入消息列表。**返回新数组，不改入参。**
 *
 * 只有"最后一条 assistant 且仍在 streaming"才接受片段 ——
 * 这正是事件通道乱序/迟到时不该污染历史的那道闸（与旧行为等价，但判据显式化）。
 */
export function applyChunk(
  messages: readonly ChatMessage[],
  delta: string,
): ChatMessage[] {
  if (!delta) return messages.slice()
  const i = lastAssistantIndex(messages)
  if (i < 0) return messages.slice()
  const last = messages[i]
  if (!last || !last.streaming) return messages.slice()
  const next = messages.slice()
  next[i] = { ...last, content: last.content + delta }
  return next
}

/**
 * 收尾：把回复置为完成，并在**内容为空**时以 `fallbackText` 兜底填充。
 *
 * 兜底是刻意的：事件通道在浏览器环境收不到（见 `api/eventBridge.ts`），
 * `invoke` 的返回值才是可靠内容 —— 发出去了就一定要能看到。
 */
export function settleReply(
  messages: readonly ChatMessage[],
  fallbackText: string,
): ChatMessage[] {
  const i = lastAssistantIndex(messages)
  if (i < 0) return messages.slice()
  const last = messages[i]
  if (!last) return messages.slice()
  const next = messages.slice()
  next[i] = {
    ...last,
    content: last.content || fallbackText,
    streaming: false,
  }
  return next
}

/** 把错误挂到最后一条 assistant 消息上（不弹全局窗）。 */
export function failReply(
  messages: readonly ChatMessage[],
  error: string,
): ChatMessage[] {
  const i = lastAssistantIndex(messages)
  if (i < 0) return messages.slice()
  const last = messages[i]
  if (!last) return messages.slice()
  const next = messages.slice()
  next[i] = { ...last, streaming: false, error }
  return next
}

// ---------------------------------------------------------------- 发送前置判据

export interface SendGuard {
  /** 是否可以发送。 */
  ok: boolean
  /** 不可发送的原因（空串 = 可以）。 */
  reason: string
}

/**
 * 发送前置判据的**唯一定义处**（此前散在组件与 store 里各写一遍，容易走偏）。
 *
 * 三条：有内容、没有请求在飞、模式必须是已知的两个之一。
 */
export function canSend(input: { text: string; streaming: boolean; mode: string }): SendGuard {
  if (!input.text.trim()) return { ok: false, reason: '内容为空' }
  if (input.streaming) return { ok: false, reason: '上一次回复仍在生成' }
  if (input.mode !== 'consult' && input.mode !== 'workspace') {
    return { ok: false, reason: `未知模式：${input.mode}` }
  }
  return { ok: true, reason: '' }
}
