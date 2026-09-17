/**
 * AI Model Domain —— Provider 注册机制（TECH-03-A · TASK-02 / TASK-05）
 *
 * ## 位置与分工（别和 Python 侧搞混）
 * ```
 * Python 侧  ai/providers/registry.py  PROVIDERS  ← **L0 能力真相**（"系统有哪些 Provider"）
 *                    ↓ core ai_info → UI 只读
 * UI 侧      本文件 ProviderRegistry            ← **UI 侧投影 + 适配器选择**
 * ```
 * 本文件**不复制**能力真相，只把 L0 的描述包装成带适配器的可调用对象。
 * 新增一个 Provider 仍然只需改 Python 侧一行登记 —— 本文件不需要动
 * （这正是"Provider 抽象是否成功"的判据，Python 侧 README 已写明）。
 *
 * ## 为什么把 IO 抽成 `ModelIo` 注入
 * 领域层一旦自己 `fetch` / `invoke`，就再也不能在 Node 里直接跑测试，
 * 也会把"能不能列出模型"和"怎么列模型"焊死。这里把 IO 变成入参：
 * 生产环境注入经 core 的实现（`ports.ts`），验收脚本注入假的实现。
 *
 * ## 三类适配器的差别（这就是 TASK-05 的答案骨架）
 * | 类型 | 代表 | 需要 key | 失败语义 | 发现模型 |
 * |------|------|:--------:|----------|----------|
 * | `api` | openai / deepseek / compatible | 是 | `no_api_key`（本地短路，不发请求） | `/models` |
 * | `local` | ollama / lmstudio | 否 | `local_model_down`（不可达即进程没起） | `/api/tags`、`/v1/models` |
 * | `agent` | user-agent | 否 | `not_implemented`（协议未定稿） | 无（协议未定稿） |
 */

import type { ConnectionType } from './model'

// ---------------------------------------------------------------- 描述与结果

/** Provider 的 UI 侧投影（字段取自 L0 `ProviderMeta`，命名按 UI 习惯）。 */
export interface ProviderDescriptor {
  id: string
  label: string
  connectionType: ConnectionType
  defaultEndpoint: string
  defaultModel: string
  needsKey: boolean
  /** `false` = 占位 Provider（能力未实现，UI 应置灰）。 */
  enabled: boolean
  note: string
  /** L0 声明支持的能力键（`chat` / `stream` / `models` …）。 */
  capabilities: string[]
}

export interface ProviderDescriptorInput {
  id: string
  label?: string
  connectionType?: ConnectionType
  defaultEndpoint?: string
  defaultModel?: string
  needsKey?: boolean
  enabled?: boolean
  note?: string
  capabilities?: string[]
}

export interface ModelDescriptor {
  provider: string
  model: string
  name: string
  /** `remote` = 从服务端拉到；`declared` = Provider 的默认模型（服务端不可达时的兜底）。 */
  source: 'remote' | 'declared'
}

/** 失败码，与 Python `ProviderError` 的码表**同源**（这样 UI 文案映射只写一份）。 */
export const PROVIDER_ERROR_CODES = [
  'ok',
  'no_api_key',
  'unreachable',
  'local_model_down',
  'auth_failed',
  'timeout',
  'rate_limit',
  'bad_response',
  'not_implemented',
  'unknown',
] as const
export type ProviderErrorCode = (typeof PROVIDER_ERROR_CODES)[number]

export interface ConnectionTestResult {
  provider: string
  ok: boolean
  code: ProviderErrorCode
  message: string
  /** 连通时拉到的模型数（0 也代表连通 —— 接口通了但没装模型）。 */
  modelCount: number
  ms: number
  checkedAt: number
  /** 本次测试是否真的发了请求（`no_api_key` 等本地短路为 `false`）。 */
  probed: boolean
}

/** 领域层需要但**不自己实现**的 IO。 */
export interface ModelIo {
  /** 拉取某 Provider 的远端模型列表。不可达时**应返回空数组**（不是抛错）。 */
  listRemoteModels(
    providerId: string,
    opts: { apiBase?: string; model?: string },
  ): Promise<string[]>
  /**
   * Agent 健康探测（TECH-06-A）。
   *
   * **可选**：不实现时 `AgentAdapter` 如实回退到 `not_implemented`（不假装探测过）。
   * 实现方应当复用既有 core 能力（`agents_list` + `agent_health`），**不新增后端命令**。
   *
   * 语义约定：`notFound` 表示"没有注册匹配的 Agent"（缺前提 → 未配置），
   * 与"注册了但健康检查失败"（→ 离线/失败）是两件事，必须分开报。
   */
  agentHealth?(target: { name?: string; url?: string }): Promise<{
    ok: boolean
    /** 实际探测的 URL（core 回填）。 */
    healthUrl?: string
    /** 健康检查的 HTTP 状态码。 */
    status?: number
    /** 失败原因（core 或网络层的原文）。 */
    error?: string
    /** 没有注册匹配的 Agent（≠ 健康检查失败）。 */
    notFound?: boolean
  }>
}

/** 测试/发现时除 IO 之外的外部事实。 */
export interface ProbeContext {
  /** 覆盖 endpoint（用户自定义 base）。 */
  apiBase?: string
  /** 覆盖模型。 */
  model?: string
  /** 该 Provider 是否已在系统凭据库里配了 key（**只问有无，不问值**）。 */
  hasSecret?: boolean
}

// ---------------------------------------------------------------- 适配器

export interface ProviderAdapter {
  readonly connectionType: ConnectionType
  /** 测试连接。**不抛错** —— 失败也是一种结果（返回 `ok:false` + code）。 */
  testConnection(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx?: ProbeContext,
  ): Promise<ConnectionTestResult>
  /** 发现模型。**不抛错** —— 拉不到就返回声明的默认模型（或空数组）。 */
  discoverModels(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx?: ProbeContext,
  ): Promise<ModelDescriptor[]>
}

/** 把 core / sidecar 的错误文本归类成码（与 Python 侧码表同源）。 */
export function classifyProbeError(raw: unknown): { code: ProviderErrorCode; message: string } {
  const text = raw instanceof Error ? raw.message : String(raw ?? '')
  const t = text.toLowerCase()
  const rules: Array<[ProviderErrorCode, RegExp]> = [
    ['no_api_key', /no_api_key|尚未配置.*key|api ?key.*(缺失|未配置)/i],
    ['auth_failed', /auth_failed|401|403|被拒绝|invalid[_ ]api[_ ]key|unauthorized/i],
    ['rate_limit', /rate_limit|429|too many requests|过于频繁/i],
    ['timeout', /timeout|timed out|超时/i],
    ['local_model_down', /local_model_down|connection refused|actively refused|拒绝连接/i],
    ['unreachable', /unreachable|不可达|dns|name or service|network|网络/i],
    ['not_implemented', /not_implemented|尚未开放|not implemented/i],
    ['bad_response', /bad_response|list_models_failed|返回体|malformed/i],
  ]
  for (const [code, re] of rules) {
    if (re.test(t)) return { code, message: text || code }
  }
  return { code: 'unknown', message: text || '未知错误' }
}

function result(
  d: ProviderDescriptor,
  ok: boolean,
  code: ProviderErrorCode,
  message: string,
  modelCount: number,
  ms: number,
  probed: boolean,
): ConnectionTestResult {
  return {
    provider: d.id,
    ok,
    code,
    message,
    modelCount,
    ms,
    checkedAt: Date.now(),
    probed,
  }
}

async function timed<T>(fn: () => Promise<T>): Promise<{ value: T; ms: number }> {
  const t0 = Date.now()
  const value = await fn()
  return { value, ms: Date.now() - t0 }
}

/** 云 API：需要 key；缺 key **本地短路**（不发请求 —— 这是可断言的行为）。 */
export class CloudApiAdapter implements ProviderAdapter {
  readonly connectionType: ConnectionType = 'api'

  async testConnection(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ConnectionTestResult> {
    if (d.needsKey && !ctx.hasSecret) {
      return result(d, false, 'no_api_key', `${d.label} 尚未配置 API Key`, 0, 0, false)
    }
    try {
      const { value, ms } = await timed(() =>
        io.listRemoteModels(d.id, { apiBase: ctx.apiBase, model: ctx.model }),
      )
      return result(d, true, 'ok', `连通，${value.length} 个模型`, value.length, ms, true)
    } catch (err) {
      const { code, message } = classifyProbeError(err)
      return result(d, false, code, message, 0, 0, true)
    }
  }

  async discoverModels(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ModelDescriptor[]> {
    let remote: string[] = []
    try {
      remote = await io.listRemoteModels(d.id, { apiBase: ctx.apiBase, model: ctx.model })
    } catch {
      remote = []
    }
    return mergeDeclared(d, remote)
  }
}

/** 本地运行时：不需要 key；不可达即"进程没起"（语义上比 `unreachable` 更有指导性）。 */
export class LocalRuntimeAdapter implements ProviderAdapter {
  readonly connectionType: ConnectionType = 'local'

  async testConnection(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ConnectionTestResult> {
    try {
      const { value, ms } = await timed(() =>
        io.listRemoteModels(d.id, { apiBase: ctx.apiBase, model: ctx.model }),
      )
      return result(d, true, 'ok', `本地服务已就绪，${value.length} 个模型`, value.length, ms, true)
    } catch (err) {
      const { code, message } = classifyProbeError(err)
      const mapped: ProviderErrorCode =
        code === 'unreachable' || code === 'unknown' ? 'local_model_down' : code
      return result(d, false, mapped, message, 0, 0, true)
    }
  }

  async discoverModels(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ModelDescriptor[]> {
    let remote: string[] = []
    try {
      remote = await io.listRemoteModels(d.id, { apiBase: ctx.apiBase, model: ctx.model })
    } catch {
      remote = []
    }
    return mergeDeclared(d, remote)
  }
}

/**
 * Agent 接入：**健康探测复用 core 既有能力**（TECH-06-A）。
 *
 * 与普通模型的两点区别（TASK-05 的问题，这里给出一半答案）：
 * 1. 区别不在数据结构（都是 `ModelProfile`，靠 `connection.type='agent'` 分流），
 *    而在**握手协议**：Agent 需要 health 握手 + invoke 分帧，普通模型只要一次 chat；
 * 2. Agent **没有"模型列表"** —— 列表接口 (`ai_list_models`) 对它无意义，
 *    所以不能用"拉列表成功"当连通判据，必须走 `agent_health`。
 *
 * 因此本类走 `io.agentHealth()`（可选端口）。**三条诚实底线**：
 * - 端口没实现 → 如实回 `not_implemented`，`probed=false`（**不假装探测过**）；
 * - 没有注册匹配的 Agent → `not_probed` 类结果（缺前提），**不报"连接失败"**；
 * - 注册了但健康检查失败 → 才是真的失败（`unreachable` / `bad_response`）。
 */
export class AgentAdapter implements ProviderAdapter {
  readonly connectionType: ConnectionType = 'agent'

  async testConnection(
    d: ProviderDescriptor,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ConnectionTestResult> {
    // ① 未开放 / 未实现端口 → 不发请求（probed=false 是关键：UI 不能把它显示成"连接失败"）
    if (!io.agentHealth) {
      const why = d.enabled
        ? '当前环境没有接入 Agent 健康探测端口'
        : d.note || 'Agent 接入尚未开放'
      return result(d, false, 'not_implemented', why, 0, 0, false)
    }

    // ② 真探测：名字优先（注册名），否则按 endpoint 匹配已注册 Agent
    const { value, ms } = await timed(() =>
      io.agentHealth!({ url: ctx.apiBase || d.defaultEndpoint }),
    )

    if (value.notFound) {
      // **没连过** ≠ 连不上 —— 缺前提，报 not_implemented 且 probed=false
      return result(d, false, 'not_implemented', '尚未注册该 Agent（无法探测）', 0, ms, false)
    }
    if (value.ok) {
      return result(d, true, 'ok', `Agent 健康检查通过${value.healthUrl ? `（${value.healthUrl}）` : ''}`, 1, ms, true)
    }
    const code: ProviderErrorCode = value.status !== undefined && value.status !== 200
      ? 'bad_response'
      : 'unreachable'
    return result(d, false, code, value.error || `健康检查未通过（status=${value.status ?? 0}）`, 0, ms, true)
  }

  async discoverModels(d: ProviderDescriptor): Promise<ModelDescriptor[]> {
    // Agent 没有"模型列表"的概念 —— 它就一个端点。
    return d.defaultModel ? [toDescriptor(d, d.defaultModel, 'declared')] : []
  }
}

function toDescriptor(
  d: ProviderDescriptor,
  model: string,
  source: 'remote' | 'declared',
): ModelDescriptor {
  return { provider: d.id, model, name: model, source }
}

/** 远端列表 + 声明的默认模型合并去重（默认模型排在最前，便于 UI 预选）。 */
function mergeDeclared(d: ProviderDescriptor, remote: string[]): ModelDescriptor[] {
  const remoteSet = new Set(remote.map((m) => (m ?? '').trim()).filter(Boolean))
  const seen = new Set<string>()
  const out: ModelDescriptor[] = []
  if (d.defaultModel) {
    seen.add(d.defaultModel)
    // 远端也有它 → 标签用 remote（那是真的探测到了，比"声明"强）
    out.push(toDescriptor(d, d.defaultModel, remoteSet.has(d.defaultModel) ? 'remote' : 'declared'))
  }
  for (const m of remoteSet) {
    if (seen.has(m)) continue
    seen.add(m)
    out.push(toDescriptor(d, m, 'remote'))
  }
  return out
}

/** 内置三类适配器（可被 `registerAdapter` 覆盖）。 */
export const DEFAULT_ADAPTERS: Readonly<Record<ConnectionType, ProviderAdapter>> = {
  api: new CloudApiAdapter(),
  local: new LocalRuntimeAdapter(),
  agent: new AgentAdapter(),
}

// ---------------------------------------------------------------- 连接类型推断

/** 已知的本地运行时 id（与 L0 registry 对齐，新增本地 Provider 时在此补一行）。 */
export const LOCAL_PROVIDER_IDS: readonly string[] = ['ollama', 'lmstudio']
/** 已知的 Agent 接入 id。 */
export const AGENT_PROVIDER_IDS: readonly string[] = ['user-agent']

function hostIsLoopback(endpoint: string): boolean {
  try {
    const host = new URL(endpoint).hostname.toLowerCase()
    return host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '[::1]'
  } catch {
    return false
  }
}

/**
 * 推断连接类型（用于把 L0 的 Provider 投影成描述符时补 `connectionType`）。
 *
 * 判据顺序：显式声明 → 已知 id 表 → 无 key 且指向本机 → id 含 agent → 兜底 `api`。
 * 推断结果**可被显式覆盖** —— 推断只是省一次手写，不是规则。
 */
export function inferConnectionType(input: ProviderDescriptorInput): ConnectionType {
  if (input.connectionType) return input.connectionType
  const id = input.id.trim().toLowerCase()
  if (LOCAL_PROVIDER_IDS.includes(id)) return 'local'
  if (AGENT_PROVIDER_IDS.includes(id)) return 'agent'
  if (!(input.needsKey ?? true) && input.defaultEndpoint && hostIsLoopback(input.defaultEndpoint)) {
    return 'local'
  }
  if (/agent/.test(id)) return 'agent'
  return 'api'
}

export function normalizeDescriptor(input: ProviderDescriptorInput): ProviderDescriptor {
  const id = input.id.trim().toLowerCase()
  return {
    id,
    label: input.label?.trim() || id,
    connectionType: inferConnectionType({ ...input, id }),
    defaultEndpoint: input.defaultEndpoint?.trim() ?? '',
    defaultModel: input.defaultModel?.trim() ?? '',
    needsKey: input.needsKey ?? true,
    enabled: input.enabled ?? true,
    note: input.note ?? '',
    capabilities: [...(input.capabilities ?? [])],
  }
}

// ---------------------------------------------------------------- ProviderRegistry（TASK-02）

interface Entry {
  descriptor: ProviderDescriptor
  adapter: ProviderAdapter
}

/**
 * Provider 注册中心。
 *
 * **幂等**：`registerProvider()` 重复登记同一 id 会**覆盖**（不是报错）——
 * 因为正常路径就是"每次启动从 L0 重新投影一遍"，重复登记不是异常。
 */
export class ProviderRegistry {
  private readonly entries = new Map<string, Entry>()
  private readonly adapters = new Map<ConnectionType, ProviderAdapter>()

  constructor(adapters?: Partial<Record<ConnectionType, ProviderAdapter>>) {
    for (const t of Object.keys(DEFAULT_ADAPTERS) as ConnectionType[]) {
      this.adapters.set(t, DEFAULT_ADAPTERS[t])
    }
    if (adapters) {
      for (const [k, v] of Object.entries(adapters)) {
        if (v) this.adapters.set(k as ConnectionType, v)
      }
    }
  }

  /** 替换某一连接类型的适配器（新增连接类型时用）。 */
  registerAdapter(type: ConnectionType, adapter: ProviderAdapter): void {
    this.adapters.set(type, adapter)
  }

  /** 注册 Provider（TASK-02）。未显式给适配器时按 `connectionType` 选默认适配器。 */
  registerProvider(
    input: ProviderDescriptorInput,
    adapter?: ProviderAdapter,
  ): ProviderDescriptor {
    const descriptor = normalizeDescriptor(input)
    if (!descriptor.id) throw new Error('registerProvider 需要非空 id')
    const chosen = adapter ?? this.adapters.get(descriptor.connectionType)
    if (!chosen) {
      throw new Error(`没有可用于 connectionType=${descriptor.connectionType} 的适配器`)
    }
    this.entries.set(descriptor.id, { descriptor, adapter: chosen })
    return { ...descriptor, capabilities: [...descriptor.capabilities] }
  }

  /** 批量注册（`hydrate()` 从 L0 投影时用）。 */
  registerMany(inputs: readonly ProviderDescriptorInput[]): ProviderDescriptor[] {
    return inputs.map((i) => this.registerProvider(i))
  }

  /** 移除 Provider（TASK-02）。返回是否真的移除了（未知 id 返回 `false`，不抛错）。 */
  removeProvider(id: string): boolean {
    return this.entries.delete(id.trim().toLowerCase())
  }

  listProviders(opts: { enabledOnly?: boolean } = {}): ProviderDescriptor[] {
    return [...this.entries.values()]
      .filter((e) => (opts.enabledOnly ? e.descriptor.enabled : true))
      .map((e) => ({ ...e.descriptor, capabilities: [...e.descriptor.capabilities] }))
  }

  getProvider(id: string): ProviderDescriptor | null {
    const e = this.entries.get(id.trim().toLowerCase())
    return e ? { ...e.descriptor, capabilities: [...e.descriptor.capabilities] } : null
  }

  has(id: string): boolean {
    return this.entries.has(id.trim().toLowerCase())
  }

  size(): number {
    return this.entries.size
  }

  clear(): void {
    this.entries.clear()
  }

  adapterFor(id: string): ProviderAdapter | null {
    return this.entries.get(id.trim().toLowerCase())?.adapter ?? null
  }

  /**
   * 获取模型列表（TASK-02 `getModels`）。
   * 未知 Provider → `[]`（不抛错：列表接口的语义是"有什么给你什么"）。
   */
  async getModels(
    id: string,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ModelDescriptor[]> {
    const e = this.entries.get(id.trim().toLowerCase())
    if (!e || !e.descriptor.enabled) return []
    return e.adapter.discoverModels(e.descriptor, io, ctx)
  }

  /** 测试连接（TASK-02 `testConnection`）。未知 Provider → `not_implemented`。 */
  async testConnection(
    id: string,
    io: ModelIo,
    ctx: ProbeContext = {},
  ): Promise<ConnectionTestResult> {
    const key = id.trim().toLowerCase()
    const e = this.entries.get(key)
    if (!e) {
      const stub = normalizeDescriptor({ id: key || id })
      return result(stub, false, 'not_implemented', `未注册的 Provider：${id}`, 0, 0, false)
    }
    return e.adapter.testConnection(e.descriptor, io, ctx)
  }
}
