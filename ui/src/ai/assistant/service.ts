/**
 * AI 助手应用层 —— 应用服务（TECH-05-D §P1-A）
 *
 * ## 它在数据链里的位置（任务书 §5 要求的那个入口）
 * ```
 *   /ai 助手页（AiView.vue）   AI 侧栏（AiSidebar.vue）
 *              │  ① 只说"用户想发这句话 / 想中断 / 想预览上下文"
 *              ▼
 *       本文件（AI Application Service）        ← **本轮新增的唯一入口**
 *              │  ② 解析目标：canonical 优先（读共享 ModelRegistry）
 *              │  ③ 权限边界：咨询模式归零授权范围
 *              │  ④ 装配参数：buildChatArgs()
 *              ▼
 *   AI Transport Port（transport.ts）→ core → sidecar → Provider
 * ```
 *
 * 于是"用哪个模型"这个问题的答案**只有一条路径**：
 * 它不是页面决定的、不是 store 决定的、也不是传输层决定的，
 * 而是本服务按冻结契约的 `resolutionOrder` 从 canonical 解出来的。
 *
 * ## 本服务刻意是**无状态**的
 * 会话状态（当前会话、消息列表、在飞与否）由 `stores/ai.ts` 持有 ——
 * 本层不存一份，因此不存在"同一个会话有两个故事"的可能。
 * 本层提供的是**规则**（怎么解析目标、怎么划边界、怎么装参数），
 * 规则可以被枚举验证，状态不能。这条分工是有意的。
 *
 * ## 不 import Vue
 * 同 `ai/model/*`：本层能被编译成 JS 在 Node 里直接跑，
 * 验收脚本因此可以拿 `memoryTransport()` 驱动**真实编排逻辑**做断言，
 * 而不是只能"读代码"。
 */

import type { ModelRegistry } from '@/ai/model/registry'

import type { AiMode } from './session'
import {
  buildChatArgs,
  grantedScopes,
  permissionTextOf,
  requestReady,
  resolveForUi,
  type ChatArgs,
  type ResolvedTarget,
  type Scope,
  type ScopePrefs,
  type TargetCandidate,
} from './request'
import type { AiTransport, ChatResult, ContextPreview } from './transport'

// ---------------------------------------------------------------- 依赖

/**
 * 各层候选值的读取器。
 *
 * 全部可选：缺省时本服务只从 `registry` 现算（canonical + firstEnabled），
 * `suggestion` / `headlessDefault` 需要读 core config，属于 IO，
 * 由组合根（`bridge.ts`）注入 —— 于是本文件保持零 IO、可 Node 直跑。
 */
export interface AssistantTargetSources {
  /** L1 canonical（缺省取 `registry.getDefault().canonical`）。 */
  canonical(): Partial<TargetCandidate> | null
  /** L3 建议层：模式 `ai_profile` 的运行时投影。 */
  suggestion(): Promise<Partial<TargetCandidate> | null>
  /** L4 无 UI 调用者回退：`ai.default_provider`。 */
  headlessDefault(): Promise<Partial<TargetCandidate> | null>
  /** L0 兜底：注册表里第一个可用 Provider。 */
  firstEnabled(): Partial<TargetCandidate> | null
}

export interface AssistantDeps {
  registry: ModelRegistry
  transport: AiTransport
  /** 覆盖任意读取器（验收脚本注入固定值用）。 */
  sources?: Partial<AssistantTargetSources>
  /** 时间源（可注入，便于验收断言确定的时间戳）。 */
  now?: () => number
}

// ---------------------------------------------------------------- 请求准备结果

export interface PrepareInput {
  mode: AiMode
  /** 用户在权限面板里的意愿开关。 */
  scopePrefs: ScopePrefs
  /** 对话历史（不含占位的流式回复条）。 */
  history: ReadonlyArray<{ role: string; content: string }>
  promptKey?: string
  temperature?: number
  maxTokens?: number
}

export interface PreparedRequest {
  /** 是否可发。`false` 时 `reason` 给人话（UI 直接显示）。 */
  ok: boolean
  reason: string
  /** 装配好的参数（`ok=false` 时仍给出，便于验收查看"本来会发什么"）。 */
  args: ChatArgs
  /** 本次解析出的目标（provider/model + 命中层）。 */
  target: ResolvedTarget
  /** 权限提示文案（与 `granted` 同源）。 */
  permission: string
  /** 本次实际授权的来源。 */
  granted: Scope[]
}

export interface AssistantService {
  /** 共享的 ModelRegistry（只读使用；本层不写 canonical）。 */
  readonly registry: ModelRegistry
  /** 传输端口（验收时可替换为内存实现）。 */
  readonly transport: AiTransport
  /** 按冻结契约解析本次请求目标。**UI 路径，无 `explicit` 通道**。 */
  resolve(): Promise<ResolvedTarget>
  /** 解析目标 + 划权限边界 + 装配参数（发送前的一次性准备）。 */
  prepare(input: PrepareInput): Promise<PreparedRequest>
  /** 发起对话（参数必须是 `prepare()` 的产物）。 */
  chat(args: ChatArgs): Promise<ChatResult>
  /** 中断当前生成。 */
  cancel(): Promise<void>
  /** 预览本次会带哪些上下文。 */
  previewContext(mode: AiMode, scopePrefs: ScopePrefs): Promise<ContextPreview>
  /** 订阅 Registry 变更（目标可能变化 → UI 应刷新）。 */
  subscribe(fn: (reason: string, revision: number) => void): () => void
  /** 订阅流式增量。 */
  onChunk(fn: (chunk: { delta: string }) => void): () => void
  /** 订阅响应结束。 */
  onDone(fn: () => void): () => void
}

// ---------------------------------------------------------------- 缺省读取器

function defaultSources(registry: ModelRegistry): AssistantTargetSources {
  return {
    canonical() {
      const d = registry.getDefault()
      const c = d.canonical
      return { provider: c.provider, model: c.model, apiBase: c.apiBase }
    },
    async suggestion() {
      // 缺省无建议层来源：模式 ai_profile 的投影由组合根注入
      return null
    },
    async headlessDefault() {
      return null
    },
    firstEnabled() {
      const p = registry.listProviders().find((x) => x.enabled)
      if (!p) return null
      return { provider: p.id, model: p.defaultModel, apiBase: p.defaultEndpoint }
    },
  }
}

// ---------------------------------------------------------------- 门面

export function createAssistantService(deps: AssistantDeps): AssistantService {
  const { registry, transport } = deps
  const fallback = defaultSources(registry)
  const pick = <K extends keyof AssistantTargetSources>(k: K): AssistantTargetSources[K] =>
    (deps.sources?.[k] as AssistantTargetSources[K] | undefined) ?? fallback[k]

  const api: AssistantService = {
    registry,
    transport,

    async resolve(): Promise<ResolvedTarget> {
      // 五层按契约顺序取第一个有值的。**UI 路径不提供 explicit** ——
      // `resolveForUi` 的签名里就没有那个字段（见 request.ts 的说明）。
      return resolveForUi({
        canonical: pick('canonical')(),
        suggestion: await pick('suggestion')(),
        headlessDefault: await pick('headlessDefault')(),
        firstEnabled: pick('firstEnabled')(),
      })
    },

    async prepare(input: PrepareInput): Promise<PreparedRequest> {
      const target = await api.resolve()
      const args = buildChatArgs({
        target,
        mode: input.mode,
        history: input.history,
        scopePrefs: input.scopePrefs,
        promptKey: input.promptKey,
        temperature: input.temperature,
        maxTokens: input.maxTokens,
      })
      const ready = requestReady(args)
      return {
        ok: ready.ok,
        reason: ready.reason,
        args,
        target,
        // 提示与授权同源（同一个 grantedScopes 出口），不会各说各话
        permission: permissionTextOf(input.mode, input.scopePrefs),
        granted: grantedScopes(input.mode, input.scopePrefs),
      }
    },

    chat(args: ChatArgs): Promise<ChatResult> {
      // 传输层只传不决策（契约 transport.mayDecide = false）：给它什么发什么
      return transport.chat(args)
    },

    cancel(): Promise<void> {
      return transport.cancel()
    },

    previewContext(mode: AiMode, scopePrefs: ScopePrefs): Promise<ContextPreview> {
      // 咨询模式**根本不去问** core 要上下文（而不是"问了但不用"）
      if (mode !== 'workspace') return Promise.resolve({ context: null, usedScopes: [] })
      return transport.previewContext(mode, scopePrefs)
    },

    subscribe(fn) {
      return registry.subscribe((m) => fn(m.reason, m.revision))
    },

    onChunk(fn) {
      return transport.onChunk(fn)
    },

    onDone(fn) {
      return transport.onDone(fn)
    },
  }

  return api
}
