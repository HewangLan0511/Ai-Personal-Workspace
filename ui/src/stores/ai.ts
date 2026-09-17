/**
 * AI 助手状态（阶段5 → TECH-05-D §P1-A 收敛）
 *
 * ## 本轮它变成了什么
 * 此前本文件同时干三件事：**持会话状态**、**拼请求参数**、**调 core 发请求**。
 * 三件事混在一处，"谁决定用哪个模型"就说不清 —— 而 TECH-05-D 的验收要求
 * 「AI 助手页 / 侧栏 / 请求入口看到的当前模型全部来自 `getSharedRegistry()`」。
 *
 * 现在职责切开了：
 * ```
 *   stores/ai.ts（本文件）        只持**状态**：会话列表、消息、在飞、UI 偏好
 *        │
 *        ▼
 *   ai/assistant/service.ts       只持**规则**：解析目标（canonical 优先）+ 权限边界 + 装配参数
 *        │
 *        ▼
 *   ai/assistant/transport.ts     只做**传输**：ai_chat / ai_cancel / ai_preview_context
 * ```
 * 于是本文件里**不再出现任何 `ai_chat` 的 invoke** —— 请求链路只有一个入口。
 *
 * ## 保留不动的三样东西（兼容性锚点，刻意保留）
 * 1. **5 个 localStorage 键**（`ui.ai.width` / `collapsed` / `provider` / `model` / `mode`）——
 *    键名是对外契约（`verify_stage5.py` 9c 按名字核对），不改名、不搬家；
 * 2. **过渡镜像键继续写**（`ui.ai.provider` / `ui.ai.model`）：老版本回滚仍能读到；
 * 3. **对外面 12 项**（providerId / model / mode / messages / currentProvider /
 *    permissionText / enabledScopes / setProvider / setModel / setMode / init / send）。
 *
 * ## 关于"当前模型"
 * 本文件**不持有**当前模型。它只有"用户在选择器上点了什么"（`providerId` / `model`），
 * 那是**界面选择**，改动时会写进 canonical（`syncCanonicalNow`）。
 * 「当前模型是什么」永远去 canonical 问（页面与侧栏都用 `useCurrentModel()` 投影同一份）。
 */

import { defineStore } from 'pinia'

import { getSharedAssistant } from '@/ai/assistant/bridge'
import {
  SCOPE_LABEL,
  SCOPES,
  defaultScopePrefs,
  permissionTextOf,
  type Scope,
  type ScopePrefs,
} from '@/ai/assistant/request'
import {
  SESSION_STATUS_LABEL,
  UNTITLED_SESSION,
  applyChunk,
  canSend,
  createSession,
  currentSessionOf,
  failReply,
  newMessageId,
  sessionStatusOf,
  settleReply,
  sessionsOf,
  titleOf,
  type AiMode,
  type AiSession,
  type ChatMessage,
  type SessionStatus,
} from '@/ai/assistant/session'
import type { ChatArgs } from '@/ai/assistant/request'
import { humanizeAiError } from '@/ai/assistant/transport'
import { resolveAtBoot, subscribeCanonical, syncSelection } from '@/ai/model/bridge'
import { inTauri, invokeCore } from '@/api/client'
import { logger } from '@/utils/logger'

// 对外类型/常量的**再导出**：`AiSidebar.vue` 等既有消费者 import 路径不变。
// 定义处只有一处（`ai/assistant/session.ts` / `request.ts`），本文件不另立一份。
export type { AiMode, ChatMessage, Scope, SessionStatus }
export { SCOPE_LABEL, SCOPES }

export interface ProviderInfo {
  id: string
  label: string
  defaultBase: string
  defaultModel: string
  needsKey: boolean
  enabled: boolean
  note: string
  capabilities: string[]
  hasKey?: boolean
  keyMask?: string
  credentialRef?: string
}

interface AiState {
  mode: AiMode
  providers: ProviderInfo[]
  /** 界面选择（不是"当前模型" —— 当前模型请读 canonical）。 */
  providerId: string
  model: string
  apiBase: string
  /** 会话列表（应用层状态；本轮不落库，见报告"尚未完成的真实 AI 能力"）。 */
  sessions: AiSession[]
  /** 当前会话 id（空串 = 该模式下还没有会话）。 */
  sessionId: string
  streaming: boolean
  initialized: boolean
  /** 侧栏宽度（px），持久化 */
  width: number
  collapsed: boolean
  /** 上下文来源开关（仅 workspace 模式生效；consult 下会被应用层归零） */
  enabledScopes: ScopePrefs
  /** 上一次**请求**的错误（该条消息也会挂一份）。会话状态 `error` 判的就是它。 */
  lastError: string
  /**
   * **连接**错误（核心服务不可达 / Provider 列表拉不到）。
   *
   * 与 `lastError` 分开是刻意的：这两件事的处置完全不同 ——
   * "上次请求失败"是**会话**的状态（该重试该换模型），
   * "核心服务没起来"是**环境**的状态（界面照常可用，只是发不出去）。
   * 混用会让新开的空会话一进来就显示"上次请求失败"，属于错误的归因。
   */
  connectionError: string
  /** 本次请求实际使用的上下文来源（core 返回，用于"权限提示"与核对） */
  usedScopes: string[]
  /** 凭据库后端（windows-credential-manager / memory） */
  credentialBackend: string
  /** 对话标签（workspace 模式下的 #模式 #项目） */
  contextTags: string[]
  /**
   * 上一次实际发出的请求参数（**只读快照**，供 UI 展示与验收断言）。
   * 写入点唯一：`send()` 里 `assistant.prepare()` 的产物。
   */
  lastRequest: ChatArgs | null
  /**
   * TECH-04 §一：本次会话选择的**来源**（canonical 解析结果）。
   * `core` = 契约键 / `mirror` = 过渡镜像 / `cache` = 本地缓存 / `selection` = 界面选择（已前向写入）/ `none`。
   * 只用于可观测与验收断言，不参与任何判断。
   */
  canonicalSource: string
  /** 上面那个来源的人话原因（进日志 / 验收输出）。 */
  canonicalReason: string
}

const WIDTH_KEY = 'ui.ai.width'
const COLLAPSED_KEY = 'ui.ai.collapsed'
const PROVIDER_KEY = 'ui.ai.provider'
const MODEL_KEY = 'ui.ai.model'
const MODE_KEY = 'ui.ai.mode'

/** TECH-04 §一：canonical 订阅只挂一次（store 是单例）。 */
let canonicalBound = false
/** 事件订阅只挂一次（事件桥是单例，重复绑定会重复追加文本）。 */
let eventsBound = false

/** 本地兜底读写（浏览器环境 / core 不可达时）。 */
function lsGet(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
function lsSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* 隐私模式下 localStorage 可能不可用 —— 忽略，不影响功能 */
  }
}

/**
 * 持久化：写 localStorage（UI 的即时读源）**并**写 core 的 config 表（落库副本）。
 *
 * 两处都写是刻意的：
 * - `localStorage` 保证交互即时可用（浏览器环境也能跑）；
 * - core 的 `config` 表保证"重启后保持"有**落库**证据 —— 验收项 9 判的就是它
 *   （webview 的 localStorage 存在 Tauri 缓存目录里，外部脚本够不着，无法作为判据）。
 *
 * 只写不读：UI 的读源保持单一（localStorage），避免启动期与 core 的时序耦合。
 * core 不可达时**静默降级**（只落 localStorage）—— 持久化失败不该阻塞交互。
 */
function persist(key: string, value: string): void {
  lsSet(key, value)
  if (!inTauri()) return
  void invokeCore('put_config', { key, value }).catch((e) => {
    logger.warn('ai', `写入 core 配置失败（已落 localStorage）：${key} = ${String(e)}`)
  })
}

export const useAiStore = defineStore('ai', {
  state: (): AiState => ({
    mode: (lsGet(MODE_KEY, 'consult') as AiMode) || 'consult',
    providers: [],
    providerId: lsGet(PROVIDER_KEY, ''),
    model: lsGet(MODEL_KEY, ''),
    apiBase: '',
    sessions: [],
    sessionId: '',
    streaming: false,
    initialized: false,
    width: Number(lsGet(WIDTH_KEY, '360')) || 360,
    collapsed: lsGet(COLLAPSED_KEY, '0') === '1',
    enabledScopes: defaultScopePrefs(),
    lastError: '',
    connectionError: '',
    usedScopes: [],
    credentialBackend: '',
    contextTags: [],
    lastRequest: null,
    canonicalSource: '',
    canonicalReason: '',
  }),

  getters: {
    /** 应用层服务（解析 + 边界 + 传输的唯一入口）。 */
    assistant() {
      return getSharedAssistant()
    },

    /** 当前会话（该模式下按 `sessionId` 选；没有则为 `null`）。 */
    currentSession(state): AiSession | null {
      return currentSessionOf(state.sessions, state.sessionId, state.mode)
    },

    /**
     * 消息列表 —— **当前会话的投影，不是第二份存储**。
     * 侧栏 / 页面读的都是它，因此两处必然同源。
     */
    messages(): ChatMessage[] {
      return this.currentSession?.messages ?? []
    },

    /** 当前模式下的会话（原型：两套会话互不混）。 */
    sessionsInMode(state): AiSession[] {
      return sessionsOf(state.sessions, state.mode)
    },

    /**
     * 会话状态 —— **唯一判据在 `ai/assistant/session.ts::sessionStatusOf()`**。
     * `unset` 无会话 / `empty` 空会话 / `idle` 就绪 / `loading` 生成中 / `error` 上次失败。
     */
    sessionStatus(state): SessionStatus {
      return sessionStatusOf({
        hasSession: !!currentSessionOf(state.sessions, state.sessionId, state.mode),
        messageCount: currentSessionOf(state.sessions, state.sessionId, state.mode)?.messages.length ?? 0,
        streaming: state.streaming,
        lastError: state.lastError,
      })
    },

    /** 会话状态的人话（UI 直接显示）。 */
    sessionStatusLabel(): string {
      return SESSION_STATUS_LABEL[this.sessionStatus]
    },

    /** 当前选中的 Provider 元信息。 */
    currentProvider(state): ProviderInfo | undefined {
      return state.providers.find((p) => p.id === state.providerId)
    },

    /** 是否可以向云端发请求（需要 key 的 Provider 必须有 key）。 */
    canSend(): boolean {
      const p = this.currentProvider
      if (!p) return false
      if (!p.enabled) return false
      if (p.needsKey && !p.hasKey) return false
      return true
    },

    /**
     * 权限提示文案 —— **与真正装配的授权同源**（同一个 `permissionTextOf` 出口）。
     * consult 恒为"未授权任何用户数据"。
     */
    permissionText(state): string {
      return permissionTextOf(state.mode, state.enabledScopes)
    },

    /**
     * TECH-04 §一：**本次请求将实际使用的目标**（= `send()` 发出去的值）。
     *
     * 存在的意义是"可断言"：顶栏显示的 canonical 与这个值必须一致，
     * 否则「显示模型 ≠ 实际调用模型」的老问题就回来了。
     * 值来自 `lastRequest`（`assistant.prepare()` 的产物），不是本 store 现拼的。
     */
    requestTarget(state): { provider: string; model: string; apiBase: string } {
      const r = state.lastRequest
      return { provider: r?.provider ?? '', model: r?.model ?? '', apiBase: r?.apiBase ?? '' }
    },
  },

  actions: {
    // ---- 初始化 --------------------------------------------------------

    async init(): Promise<void> {
      if (this.initialized) return
      this.initialized = true
      await this.loadProviders()
      this.bindEvents()
      // TECH-04 §一：先把"用哪个模型"收敛到 canonical（冻结落点），再让界面跟随它。
      // 顺序有讲究 —— 必须在 loadProviders 之后（选择要落在已登记的 Provider 上）。
      await this.alignWithCanonical()
      this.bindCanonical()
      // P1-A：保证当前模式至少有一个会话（空会话 ⇒ 状态 empty，页面显示引导）
      this.ensureSession()
    },

    /**
     * TECH-04 §一：启动期把会话选择与 canonical 对齐。
     *
     * ```
     *   canonical（L1 ai.provider.current / ai.model.current）
     *       ├─ 有值 → 采纳为本次会话选择（并落 localStorage，保持读源单一）
     *       └─ 为空 → 采用界面选择，并**前向写入** canonical（老数据迁移步）
     * ```
     *
     * 对齐之后：**顶栏显示的值 与 send() 实际发的值 由构造保证一致**
     * （TECH-05-D 起更进一步：请求目标由应用层在发送时从 canonical 现解，
     *  不再依赖"两边保持一致"这个约定）。
     */
    async alignWithCanonical(): Promise<void> {
      try {
        const r = await resolveAtBoot({
          provider: this.providerId,
          model: this.model,
          apiBase: this.apiBase,
        })
        this.canonicalSource = r.source
        this.canonicalReason = r.reason
        if (!r.selection.provider) return

        const changed =
          r.selection.provider !== this.providerId || r.selection.model !== this.model
        this.providerId = r.selection.provider
        this.model = r.selection.model
        if (r.selection.apiBase) this.apiBase = r.selection.apiBase
        // 界面侧读源保持单一（localStorage）；core 侧的落点由 bridge 负责。
        // 这里同时把镜像键 `ui.ai.*` 一起写掉 —— 老版本回滚仍能读到（镜像兼容）。
        if (changed || r.wroteCanonical) {
          persist(PROVIDER_KEY, this.providerId)
          persist(MODEL_KEY, this.model)
        }
      } catch (e) {
        logger.warn('ai', `canonical 对齐失败（沿用界面选择）：${String(e)}`)
      }
    },

    /**
     * TECH-04 §一：订阅 canonical。
     *
     * 只对齐一次启动值是不够的 —— canonical 可能被**界面之外**的地方改掉
     * （模型管理页、设置页）。订阅后会话选择立刻跟随，运行期也不会分叉。
     */
    bindCanonical(): void {
      if (canonicalBound) return
      canonicalBound = true
      subscribeCanonical((c) => {
        if (!c) return
        this.canonicalSource = c.source
        if (c.provider && c.provider !== this.providerId) {
          this.providerId = c.provider
          persist(PROVIDER_KEY, c.provider)
        }
        if (c.model && c.model !== this.model) {
          this.model = c.model
          persist(MODEL_KEY, c.model)
        }
      })
    },

    /** 把当前选择同步写 canonical（`setProvider` / `setModel` 的共同出口）。 */
    async syncCanonicalNow(): Promise<void> {
      const snap = await syncSelection({
        provider: this.providerId,
        model: this.model,
        apiBase: this.apiBase,
      })
      if (snap) this.canonicalSource = snap.source
    },

    async loadProviders(): Promise<void> {
      try {
        const data = await invokeCore<{
          providers: ProviderInfo[]
          credentialBackend: string
        }>('ai_info')
        this.providers = data.providers ?? []
        this.credentialBackend = data.credentialBackend ?? ''
        if (!this.providerId || !this.providers.some((p) => p.id === this.providerId)) {
          const first = this.providers.find((p) => p.enabled)
          this.providerId = first?.id ?? ''
          if (first) {
            this.model = first.defaultModel
            // 上次的选择已失效（Provider 被移除/未开放）→ 重置为默认并落库
            persist(PROVIDER_KEY, first.id)
            persist(MODEL_KEY, first.defaultModel)
          }
        }
      } catch (e) {
        // core 不可达：保留空列表，UI 显示"未连接"而非崩溃。
        // ⚠️ 写 `connectionError` 而不是 `lastError` —— 这是环境问题，不是会话失败，
        //    否则新开的空会话会一进来就显示"上次请求失败"（归因错误）。
        logger.warn('ai', `加载 Provider 列表失败：${String(e)}`)
        this.connectionError = '无法连接核心服务，AI 功能暂不可用'
      }
    },

    /**
     * 绑定流式事件（幂等）。
     *
     * P1-A：事件订阅也走应用层 —— 本文件不认识 `AI_STREAM_CHUNK` 这个名字，
     * 只接收"有一段增量到了"的语义回调。增量并入哪条消息由
     * `session.applyChunk()` 决定（只认"最后一条且仍在 streaming"）。
     */
    bindEvents(): void {
      if (eventsBound) return
      eventsBound = true
      const assistant = this.assistant
      assistant.onChunk(({ delta }) => {
        const s = this.currentSession
        if (!s) return
        s.messages = applyChunk(s.messages, delta)
      })
      assistant.onDone(() => {
        const s = this.currentSession
        if (s) s.messages = settleReply(s.messages, '')
        this.streaming = false
      })
    },

    // ---- 会话（P1-A 新增） ---------------------------------------------

    /** 新建一个空会话并切过去（"新建会话"入口）。 */
    newSession(): string {
      const s = createSession(this.mode)
      this.sessions.push(s)
      this.sessionId = s.id
      this.streaming = false
      this.lastError = ''
      this.contextTags = []
      this.usedScopes = []
      return s.id
    },

    /** 保证当前模式下有会话（没有就建一个）；返回当前会话。 */
    ensureSession(): AiSession | null {
      const cur = this.currentSession
      if (cur) {
        this.sessionId = cur.id
        return cur
      }
      const s = createSession(this.mode)
      this.sessions.push(s)
      this.sessionId = s.id
      return s
    },

    /** 切换到指定会话（只允许切当前模式下的会话，避免模式与会话不一致）。 */
    switchSession(id: string): boolean {
      const hit = sessionsOf(this.sessions, this.mode).find((s) => s.id === id)
      if (!hit) return false
      this.sessionId = hit.id
      this.streaming = false
      this.lastError = ''
      this.contextTags = []
      this.usedScopes = []
      return true
    },

    // ---- 交互 ----------------------------------------------------------

    setMode(mode: AiMode): void {
      this.mode = mode
      persist(MODE_KEY, mode)
      // 切模式时清空上下文标签（旧模式的标签不该留在新模式下）
      this.contextTags = []
      this.usedScopes = []
      this.lastError = ''
      // 切到该模式下最近活动的会话；没有则置空（状态 unset，由页面引导新建）
      const cur = currentSessionOf(this.sessions, '', mode)
      this.sessionId = cur?.id ?? ''
    },

    setProvider(id: string): void {
      this.providerId = id
      persist(PROVIDER_KEY, id)
      const p = this.providers.find((x) => x.id === id)
      if (p) {
        this.model = p.defaultModel
        this.apiBase = p.defaultBase
      }
      // TECH-04 §一：用户的选择必须**写进 canonical 才算数**（canonical 是请求依据）
      void this.syncCanonicalNow()
    },

    setModel(model: string): void {
      this.model = model
      persist(MODEL_KEY, model)
      void this.syncCanonicalNow()
    },

    setScope(scope: Scope, on_: boolean): void {
      this.enabledScopes[scope] = on_
    },

    toggleCollapsed(): void {
      this.collapsed = !this.collapsed
      persist(COLLAPSED_KEY, this.collapsed ? '1' : '0')
    },

    setWidth(px: number): void {
      const clamped = Math.max(280, Math.min(720, Math.round(px)))
      this.width = clamped
      persist(WIDTH_KEY, String(clamped))
    },

    /** 清空当前会话的消息（保持会话本身，即"重新开始"）。 */
    clear(): void {
      const s = this.currentSession
      if (s) {
        s.messages = []
        s.title = UNTITLED_SESSION
        s.updatedAt = Date.now()
      }
      this.lastError = ''
      this.contextTags = []
      this.usedScopes = []
    },

    // ---- 发送 ----------------------------------------------------------

    /**
     * 发送一条消息。
     *
     * 三步全部经应用层：
     * ① `assistant.prepare()` —— 解析目标（canonical 优先）+ 划权限边界 + 装配参数；
     * ② `assistant.chat()` —— 传输（本文件不碰 invoke）；
     * ③ `session.settleReply()` —— 收尾并把返回值兜底填进内容。
     *
     * 流式内容由事件推送；这里只负责建消息、发起、收尾。
     */
    async send(text: string): Promise<void> {
      const guard = canSend({ text, streaming: this.streaming, mode: this.mode })
      if (!guard.ok) return

      const session = this.ensureSession()
      if (!session) return

      const content = text.trim()
      this.lastError = ''
      session.messages.push({ id: newMessageId(), role: 'user', content })
      // 占位的 assistant 条：流式增量会追加到它身上
      session.messages.push({ id: newMessageId(), role: 'assistant', content: '', streaming: true })
      session.title = titleOf(session.messages)
      session.updatedAt = Date.now()
      this.streaming = true

      // 历史消息（不含占位的 streaming 条；system 由 core 装配，不在此传）
      const history = session.messages
        .filter((m) => !m.streaming)
        .map((m) => ({ role: m.role as string, content: m.content }))

      try {
        const prep = await this.assistant.prepare({
          mode: this.mode,
          scopePrefs: this.enabledScopes,
          history,
        })
        // 快照本次实际参数（**唯一写入点**：只在发送路径上写）
        this.lastRequest = prep.args
        if (!prep.ok) throw new Error(prep.reason)

        const result = await this.assistant.chat(prep.args)

        // 事件可能因环境（浏览器）未送达 —— 用返回值兜底填充完整文本，
        // 保证发出去了就一定能看到内容（不依赖事件通道）
        session.messages = settleReply(session.messages, result?.text ?? '')
        session.updatedAt = Date.now()
        this.streaming = false

        // 更新上下文标签（workspace 模式下让用户看到本次带了什么）
        await this.refreshContextTags()
      } catch (e) {
        const msg = typeof e === 'string' ? e : String(e)
        const friendly = humanizeAiError(msg)
        session.messages = failReply(session.messages, friendly)
        session.updatedAt = Date.now()
        this.streaming = false
        // 把错误挂在该条消息上（而不是全局弹窗）—— 用户能看出"哪次失败"
        this.lastError = friendly
        logger.warn('ai', `对话失败：${msg}`)
      }
    },

    /** 停止生成：立刻停掉显示（真正的 TCP 断开由前端不再消费触发）。 */
    async cancel(): Promise<void> {
      if (!this.streaming) return
      await this.assistant.cancel()
      const s = this.currentSession
      if (s) s.messages = settleReply(s.messages, '')
      this.streaming = false
    },

    /** 查询本次会带哪些上下文（用于标签显示与用户核对）。 */
    async refreshContextTags(): Promise<void> {
      if (this.mode !== 'workspace') {
        this.contextTags = []
        this.usedScopes = []
        return
      }
      try {
        const data = await this.assistant.previewContext(this.mode, this.enabledScopes)
        this.usedScopes = data.usedScopes ?? []
        const tags: string[] = []
        const ctx = data.context
        if (ctx) {
          if (ctx.modeName) tags.push(`#${ctx.modeName}`)
          if (ctx.projectDir) {
            const raw = String(ctx.projectDir)
            const base = raw.split(/[\\/]/).filter(Boolean).pop()
            if (base) tags.push(`#项目:${base}`)
          }
        }
        this.contextTags = tags
      } catch {
        this.contextTags = []
      }
    },
  },
})
