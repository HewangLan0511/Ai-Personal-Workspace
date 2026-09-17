/**
 * AI 助手应用层 —— 请求解析与权限边界（TECH-05-D §P1-A）· **纯决策，零 IO**
 *
 * ## 为什么这里能"一次说清"
 * 本项目的 AI 目标来源历史上**有五处**（模型域 `registry.ts` 头部记的实测结论）：
 * localStorage、core 同名键副本、模式 `aiProfile`、`ai.default_provider`、请求级参数。
 * 它同时被 **PW-INTEGRATION-003 冻结契约**钉死了层次：
 *
 * ```
 *   docs/contracts/fixtures/ai-provider-current.v1.valid.json
 *     canonical.role        = "single-source-of-truth"
 *     cache.mayWriteTruth   = false
 *     suggestion.mayWriteTruth = false
 *     headlessDefault.mayWriteTruth = false
 *     transport.role        = "resolved-only"  /  mayDecide = false
 *     resolutionOrder       = [request-explicit, canonical, suggestion,
 *                              headlessDefault, registry-first-enabled]
 *     readers.aiAssistantPage = "canonical"
 * ```
 *
 * 于是本文件不再"发明"规则，而是**把那份契约实现成可执行代码**：
 * - `RESOLUTION_ORDER` —— 契约里那五行，逐字搬来；
 * - `resolveTarget()` —— 按序取第一个有值的层，并如实回报 `source`；
 * - `resolveForUi()` —— **UI 调用者专用**：签名里根本没有 `explicit`，
 *   所以"AI 助手页/侧栏绕过 canonical 自己指定 provider"在类型层面就不存在；
 * - `effectiveScopes()` —— 权限边界（consult 恒不授权），与 Python
 *   `ai/context.py::permission_scope` 同源同判据。
 *
 * ## 与 core 的关系（双保险，不是二选一）
 * 真正的隔离在 sidecar：`ai/context.py::assemble()` 第一行就为 consult 返回空上下文。
 * 本层的作用是**别把数据凑齐了送过去** —— 少一次说不清的越界机会。
 * 两边判据同源（都是 `mode !== workspace ⇒ []`），不是两套说法。
 *
 * ## 零依赖
 * 不 import Vue、不 import `@/`、不碰 IO ⇒ 可在 Node 里直接枚举验证。
 */

import type { AiMode } from './session'

// ---------------------------------------------------------------- 上下文来源（唯一定义处）

/** 上下文来源开关。**与 Python `ai/context.py::SCOPES` 逐字一致**。 */
export const SCOPES = ['mode', 'apps', 'project', 'learning', 'profile'] as const
export type Scope = (typeof SCOPES)[number]

/** 来源 → 人话（UI 权限面板用）。 */
export const SCOPE_LABEL: Record<Scope, string> = {
  mode: '当前工作模式',
  apps: '已打开软件',
  project: '项目目录',
  learning: '学习状态',
  profile: '个人档案',
}

/** 来源开关表（UI 状态用）。 */
export type ScopePrefs = Record<Scope, boolean>

/** 全新用户的默认开关：全开，但**consult 下无意义**（见 `effectiveScopes`）。 */
export function defaultScopePrefs(): ScopePrefs {
  return { mode: true, apps: true, project: true, learning: true, profile: true }
}

/**
 * 该模式下**实际生效**的授权范围。**权限边界的唯一定义处。**
 *
 * ```
 *   consult   → 恒为全 false（不读任何用户数据）
 *   workspace → 按用户开关
 * ```
 *
 * 注意这与"UI 面板里勾了什么"是两件事：面板记录的是**意愿**，
 * 本函数给的是**本次请求真正会带的**东西。因此不存在
 * "切到咨询模式了但上次勾的 profile 还在生效"这类漏洞。
 */
export function effectiveScopes(mode: AiMode, prefs: ScopePrefs): ScopePrefs {
  if (mode !== 'workspace') {
    // ← 这就是权限边界。不要在下面任何分支里"顺手把 prefs 带出去"。
    return { mode: false, apps: false, project: false, learning: false, profile: false }
  }
  return { ...prefs }
}

/** 本次实际授权的来源名列表（给 UI 显示 + 验收断言，与 `effectiveScopes` 同源）。 */
export function grantedScopes(mode: AiMode, prefs: ScopePrefs): Scope[] {
  const eff = effectiveScopes(mode, prefs)
  return SCOPES.filter((s) => eff[s])
}

/**
 * 权限提示文案（UI 顶部常驻）。
 * 判据来自 `grantedScopes` —— 提示与实际装配**同源**，
 * 不会出现"提示说开了、实际没开"或反之。
 */
export function permissionTextOf(mode: AiMode, prefs: ScopePrefs): string {
  if (mode !== 'workspace') return '未授权任何用户数据'
  const list = grantedScopes(mode, prefs).map((s) => SCOPE_LABEL[s])
  return list.length ? `已授权：${list.join('、')}` : '未授权任何用户数据'
}

/**
 * 该模式下是否允许访问工作台数据。**UI 各处判断"要不要去读 Workspace/Profile"
 * 一律问这一句**，不要各写 `mode === 'workspace'`。
 */
export function mayReadWorkspace(mode: AiMode): boolean {
  return mode === 'workspace'
}

// ---------------------------------------------------------------- 目标解析（契约的 resolutionOrder）

/**
 * 目标解析顺序 —— **逐字搬自冻结契约**
 * `docs/contracts/fixtures/ai-provider-current.v1.valid.json::resolutionOrder`。
 *
 * 契约是 v1 冻结件，改这里必须同步改契约（`verify_contracts.py` 会拦）。
 */
export const RESOLUTION_ORDER = [
  'request-explicit',
  'canonical',
  'suggestion',
  'headlessDefault',
  'registry-first-enabled',
] as const

export type ResolutionLayer = (typeof RESOLUTION_ORDER)[number]

/** 解析结果里的 `source`：命中的层，或 `none`（哪都没有）。 */
export type TargetSource = ResolutionLayer | 'none'

/** 一个候选目标（各层给出来的形状一致，便于按序比较）。 */
export interface TargetCandidate {
  provider: string
  model: string
  apiBase: string
}

/** 各层的候选值（缺省即该层不可用）。 */
export interface TargetLayers {
  /** L5 请求级：**程序化调用者**显式指定（插件 / 外部 Agent）。UI 不传。 */
  explicit?: Partial<TargetCandidate> | null
  /** L1 canonical：唯一事实来源（`ModelRegistry` 的投影）。 */
  canonical?: Partial<TargetCandidate> | null
  /** L3 建议层：模式 `ai_profile` 的运行时投影（`ai.active_profile`）。 */
  suggestion?: Partial<TargetCandidate> | null
  /** L4 无 UI 调用者回退（`ai.default_provider`）。 */
  headlessDefault?: Partial<TargetCandidate> | null
  /** L0 兜底：注册表里第一个可用的 Provider。 */
  firstEnabled?: Partial<TargetCandidate> | null
}

export interface ResolvedTarget extends TargetCandidate {
  source: TargetSource
  /** 人话原因（日志 / 验收输出用，不参与判断）。 */
  reason: string
}

function norm(v: unknown): string {
  return String(v ?? '').trim()
}

/** 一个候选层是否"有值"：provider 或 model 任一非空。 */
export function targetIsSet(c: Partial<TargetCandidate> | null | undefined): boolean {
  if (!c) return false
  return !!norm(c.provider) || !!norm(c.model)
}

function normalizeTarget(c: Partial<TargetCandidate>): TargetCandidate {
  return {
    provider: norm(c.provider).toLowerCase(),
    model: norm(c.model),
    apiBase: norm(c.apiBase),
  }
}

/**
 * 按冻结契约的顺序解析本次请求目标。**纯函数**：同输入同输出。
 *
 * 实现要点：
 * - 第一个"有值"的层胜出（`request-explicit` → … → `registry-first-enabled`）；
 * - `apiBase` 逐层取第一个非空值 ——
 *   canonical 没有 apiBase 的持久键（见模型域 `selection.ts` 的同一处理），
 *   所以允许"provider/model 来自 canonical、apiBase 来自下层"的组合；
 * - `source` 如实回报命中的层，`none` 表示五层全空（UI 应显示"未配置"）。
 */
export function resolveTarget(layers: TargetLayers): ResolvedTarget {
  const cands: Array<[ResolutionLayer, Partial<TargetCandidate> | null | undefined]> = [
    ['request-explicit', layers.explicit],
    ['canonical', layers.canonical],
    ['suggestion', layers.suggestion],
    ['headlessDefault', layers.headlessDefault],
    ['registry-first-enabled', layers.firstEnabled],
  ]

  let hit: ResolutionLayer | null = null
  let picked: TargetCandidate = { provider: '', model: '', apiBase: '' }
  const apiBases: string[] = []

  for (const [layer, raw] of cands) {
    if (!targetIsSet(raw)) continue
    const t = normalizeTarget(raw as Partial<TargetCandidate>)
    if (!hit) {
      hit = layer
      picked = t
    }
    if (t.apiBase) apiBases.push(t.apiBase)
  }

  if (!hit) {
    return {
      provider: '',
      model: '',
      apiBase: '',
      source: 'none',
      reason: '契约解析顺序五层全空 → 未配置',
    }
  }

  // apiBase：命中层优先，否则取更下层的第一个（canonical 无 apiBase 键）
  const apiBase = picked.apiBase || apiBases[0] || ''

  return {
    provider: picked.provider,
    model: picked.model,
    apiBase,
    source: hit,
    reason:
      `按冻结契约 resolutionOrder 命中 ${hit}` +
      (apiBase && !picked.apiBase ? '（apiBase 来自更低层）' : ''),
  }
}

/**
 * **UI 调用者专用**解析：签名里没有 `explicit`。
 *
 * 为什么单独一个函数：契约把 `readers.aiAssistantPage` / `readers.aiSidebar`
 * 都标成 `"canonical"`。如果只提供通用 `resolveTarget()`，那么页面里
 * "顺手传一个 explicit 把 canonical 绕过去"在语法上是合法的 ——
 * 这里把那条路**从类型上删掉**，而不是靠约定。
 *
 * **注意**：仅靠类型不够。TS 类型在运行期会被擦除，JS 调用方（或任何
 * `any` 转型）硬塞一个 `explicit` 仍会被 `resolveTarget` 读到。所以这里
 * 显式**剥离** `explicit`：命名解构丢掉该键后再下传，运行期也绕不过去。
 */
export function resolveForUi(layers: Omit<TargetLayers, 'explicit'>): ResolvedTarget {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { explicit: _droppedExplicit, ...rest } = layers as TargetLayers
  void _droppedExplicit
  return resolveTarget(rest)
}

// ---------------------------------------------------------------- 请求装配（transport 的唯一输入）

/** `ai_chat` 的参数体（键名与 `core/src/api/commands.rs::ai_chat` 一致，逐项不得改名）。 */
export interface ChatArgs {
  provider: string
  model: string
  messages: Array<{ role: string; content: string }>
  mode: AiMode
  enabledScopes: ScopePrefs
  promptKey: string
  temperature: number
  maxTokens: number
  apiBase: string
}

export interface BuildChatArgsInput {
  /** 已解析的目标（来自 `resolveTarget` / `resolveForUi`）。 */
  target: TargetCandidate
  mode: AiMode
  /** 对话历史（**不含**占位的流式回复条；system 由 core 装配，不在此传）。 */
  history: ReadonlyArray<{ role: string; content: string }>
  /** 用户在权限面板里的意愿开关（consult 会被 `effectiveScopes` 归零）。 */
  scopePrefs: ScopePrefs
  promptKey?: string
  temperature?: number
  maxTokens?: number
}

/** 默认采样参数（与接线前一致，避免"顺手调参"）。 */
export const DEFAULT_TEMPERATURE = 0.7
export const DEFAULT_MAX_TOKENS = 2048

/**
 * 装配一次请求的参数体。**唯一入口** —— 此前这段拼装长在 store 的 `send()` 里，
 * 现在集中在本函数，页面 / 侧栏 / 后续真实 Transport 都从这里拿参数。
 *
 * 两个刻意的地方：
 * 1. `messages` 会**过滤掉客户端伪造的 system 角色**（与 core 的防注入一致）——
 *    系统提示词只由 core 装配，前端塞不进去；
 * 2. `mode` 与 `enabledScopes` **同源处理**：scope 一律经 `effectiveScopes()`
 *    出口，调用方无法"只改 mode 不改 scope"绕过边界。
 */
export function buildChatArgs(input: BuildChatArgsInput): ChatArgs {
  return {
    provider: norm(input.target.provider),
    model: norm(input.target.model),
    apiBase: norm(input.target.apiBase),
    mode: input.mode,
    // ← 权限边界的唯一出口：哪怕调用方把 prefs 全勾上，consult 也会被归零
    enabledScopes: effectiveScopes(input.mode, input.scopePrefs),
    promptKey: input.promptKey ?? '',
    temperature: input.temperature ?? DEFAULT_TEMPERATURE,
    maxTokens: input.maxTokens ?? DEFAULT_MAX_TOKENS,
    messages: input.history
      .filter((m) => m.role !== 'system')
      .map((m) => ({ role: m.role, content: m.content })),
  }
}

/**
 * 请求级参数是否完整可发（`provider` 必须有 —— core 靠它选 Provider 实现）。
 * 不完整时**明确失败**，不"发一个空 provider 试试看"。
 */
export function requestReady(args: ChatArgs): { ok: boolean; reason: string } {
  if (!args.provider) return { ok: false, reason: '尚未选择模型（provider 为空）' }
  return { ok: true, reason: '' }
}
