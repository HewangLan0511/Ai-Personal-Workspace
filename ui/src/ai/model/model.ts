/**
 * AI Model Domain —— 领域模型与校验（TECH-03-A · TASK-01 / TASK-06）
 *
 * ## 这一层是什么
 * 把"一个可用模型"从各家供应商的私有形态里**摘出来**，变成统一实体 `ModelProfile`。
 * 从此 UI / AI 助手 / 工作空间 Agent 都只认这一个结构，不再各自拼 `{provider, model, ...}`。
 *
 * ```
 * 改造前：  各页面各自拼 { provider, model, apiBase }  → 各写各的持久化键
 * 改造后：  ModelProfile（唯一实体）→ registry.ts（唯一读写口）→ 任意宿主
 * ```
 *
 * ## 三条设计约束（来自 TECH-03-A 执行原则）
 * 1. **不绑定厂商**：字段里没有 `openai*` / `anthropic*` 之类厂商痕迹；
 *    厂商差异收敛在 `provider`（能力真相的键）+ `connection`（怎么连）。
 * 2. **不绑定 OpenAI 格式**：`connection.type` 区分 `api | local | agent`，
 *    OpenAI 兼容只是 `api` 的一种实现细节，不进领域模型。
 * 3. **字段可扩展**：新增字段走 `metadata.extras`（显式扩展位），
 *    而不是给顶层加字段 —— 顶层的每一个字段都是契约，加之前要先想清楚。
 *
 * ## 这一层**不做**什么
 * 不发网络请求、不读 localStorage、不 import Vue、不 import `@/`。
 * 因此它可以被 Node 直接编译执行（`verify_model_registry.py` 的 T1~T5 就是这么跑的）。
 *
 * ## 安全（TASK-06 的落点）
 * 明文 API Key **在结构上就进不来**：`validateModelProfile()` 会递归扫描，
 * 命中密钥字段名或密钥形态即**拒绝整个 profile**（不是警告）。
 * 凭据只能以 **引用** 形式出现：`connection.authRef = 'pw/<provider>/<slot>'`。
 */

// ---------------------------------------------------------------- 领域模型

/** 连接类型：云 API / 本地运行时 / Agent 接入。 */
export type ConnectionType = 'api' | 'local' | 'agent'

/** 连接描述。**只描述"怎么连"，不含任何秘密**。 */
export interface ModelConnection {
  type: ConnectionType
  /** `api` / `agent` 的服务地址（`local` 可省，默认取 Provider 的 defaultEndpoint）。 */
  endpoint?: string
  /**
   * **Secret Reference**（凭据引用名），形如 `pw/deepseek/default`。
   * 真正的密钥在系统凭据库里，由 sidecar 在发起请求的瞬间取出、用完即弃。
   * ⚠️ 这里绝不允许出现明文 key —— 校验器会拒绝。
   */
  authRef?: string
  /** `local` 专用：本地模型目录 / 权重文件路径（如 `~/models/qwen2.5-7b.gguf`）。 */
  localPath?: string
  /** `agent` 专用：握手/健康检查路径（与 core `agents.rs` 的 `healthCheck` 同语义）。 */
  healthPath?: string
}

/** 能力声明。刻意只有布尔 —— 不做"能力强度"，那是评分系统的事。 */
export interface ModelCapabilities {
  chat: boolean
  vision: boolean
  coding: boolean
  agent: boolean
}

/** 运行状态（`available` 由 `check()` 更新，不由用户直接改）。 */
export interface ModelStatus {
  /** 用户是否启用（`false` 时列表仍展示，但不参与选择）。 */
  enabled: boolean
  /** 最近一次连接测试是否可用。 */
  available: boolean
  /** 最近一次连接测试时间戳（ms）。 */
  lastCheck?: number
  /** 最近一次失败码（与 Python `ProviderError.code` 同源，UI 可直接映射文案）。 */
  lastError?: string
}

/** 元数据 + 前向兼容扩展位。 */
export interface ModelMetadata {
  createdAt: number
  updatedAt: number
  /**
   * 扩展位：未来新增的、尚未进契约的结构放这里。
   * 这样"字段可扩展"不会变成"顶层字段随便加"（顶层加字段 = 改契约）。
   */
  extras?: Record<string, unknown>
}

/**
 * 统一模型实体（TASK-01）。
 *
 * 注意 `provider` 与 `connection.type` 的分工：
 * - `provider` = **能力真相的键**（对应 `ai/providers/registry.py` 的 id）；
 * - `connection.type` = **连接方式的分类**，用于选适配器。
 * 二者不冗余：同一个 `provider` 在不同部署形态下可以有不同连接类型
 * （例如 `compatible` 指向自建网关 → `api`，而未来本地网关 → `local`）。
 */
export interface ModelProfile {
  /** 稳定标识：`<provider>:<model>`（可被显式指定覆盖）。 */
  id: string
  /** Provider id（必须已在 ProviderRegistry 注册）。 */
  provider: string
  /** 展示名（UI 上给人看的）。 */
  name: string
  /** 模型标识（传给供应商的那个字符串，如 `deepseek-chat`）。 */
  model: string
  connection: ModelConnection
  capabilities: ModelCapabilities
  status: ModelStatus
  metadata: ModelMetadata
}

export const CONNECTION_TYPES: readonly ConnectionType[] = ['api', 'local', 'agent']
export const CAPABILITY_KEYS: readonly (keyof ModelCapabilities)[] = [
  'chat',
  'vision',
  'coding',
  'agent',
]

// ---------------------------------------------------------------- 构造函数

/** 补默认值（`chat` 默认 true：能连上就一定能对话，其余能力需显式声明）。 */
export function defaultCapabilities(init?: Partial<ModelCapabilities>): ModelCapabilities {
  return {
    chat: init?.chat ?? true,
    vision: init?.vision ?? false,
    coding: init?.coding ?? false,
    agent: init?.agent ?? false,
  }
}

export function emptyStatus(init?: Partial<ModelStatus>): ModelStatus {
  const out: ModelStatus = {
    enabled: init?.enabled ?? true,
    available: init?.available ?? false,
  }
  if (init?.lastCheck !== undefined) out.lastCheck = init.lastCheck
  if (init?.lastError !== undefined) out.lastError = init.lastError
  return out
}

export function newMetadata(now: number = Date.now()): ModelMetadata {
  return { createdAt: now, updatedAt: now }
}

/** `registry.add()` 的入参：允许省略一切可推导字段。 */
export interface ModelProfileInput {
  id?: string
  provider: string
  name?: string
  model: string
  /** 连接类型提示（省略则取 `connection.type`，再省略则 `api`）。 */
  connectionType?: ConnectionType
  connection?: Partial<ModelConnection>
  capabilities?: Partial<ModelCapabilities>
  status?: Partial<ModelStatus>
  extras?: Record<string, unknown>
}

/** 由 Provider id + 模型名推导稳定 id（确定性 —— 同一对永远得到同一个 id）。 */
export function deriveModelId(provider: string, model: string): string {
  return `${sanitizeIdPart(provider)}:${sanitizeIdPart(model)}`
}

/**
 * id 分段清洗：只保留 `[a-z0-9._:-]`，其余压成 `-`。
 *
 * **刻意保留 `:`** —— 本地模型的 tag 大量使用冒号（Ollama 的 `qwen2.5:7b`、
 * `llama3:8b`），把它压掉会让 id 与真实模型名对不上（`ollama:qwen2.5-7b`）。
 * id 是不透明键，解析时按**第一个** `:` 切分即可，段内再有 `:` 无害。
 */
function sanitizeIdPart(raw: string): string {
  return raw.trim().toLowerCase().replace(/[^a-z0-9._:-]+/g, '-').replace(/^[-:]+|[-:]+$/g, '')
}

/** 把"用户给的零散信息"补成一个结构完整的 `ModelProfile`（**未校验**）。 */
export function draftModelProfile(
  input: ModelProfileInput,
  now: number = Date.now(),
): ModelProfile {
  const provider = String(input.provider ?? '').trim()
  const model = String(input.model ?? '').trim()
  const conn: ModelConnection = {
    type: input.connection?.type ?? input.connectionType ?? 'api',
  }
  const src = input.connection
  if (src?.endpoint !== undefined) conn.endpoint = src.endpoint
  if (src?.authRef !== undefined) conn.authRef = src.authRef
  if (src?.localPath !== undefined) conn.localPath = src.localPath
  if (src?.healthPath !== undefined) conn.healthPath = src.healthPath

  const meta = newMetadata(now)
  if (input.extras !== undefined) meta.extras = input.extras

  return {
    id: input.id?.trim() || deriveModelId(provider, model),
    provider,
    name: input.name?.trim() || model,
    model,
    connection: conn,
    capabilities: defaultCapabilities(input.capabilities),
    status: emptyStatus(input.status),
    metadata: meta,
  }
}

// ---------------------------------------------------------------- 密钥检测（TASK-06）

/**
 * **禁止出现的字段名**（归一化后比较：去掉 `_`/`-` 并转小写）。
 * 出现即视为"有人正打算把明文密钥塞进模型配置" —— 整单拒绝。
 *
 * 注意：`authRef` 归一化为 `authref`，不在表内（它是合法的引用字段）；
 * 同理 `apiBase` → `apibase` 也不在表内。
 */
export const SECRET_KEY_NAMES: readonly string[] = [
  'apikey',
  'apikeyvalue',
  'openapikey',
  'token',
  'accesstoken',
  'refreshtoken',
  'authtoken',
  'secret',
  'clientsecret',
  'appsecret',
  'password',
  'passwd',
  'authorization',
  'bearer',
  'privatekey',
  'credential',
  'credentialsecret',
]

/** 明文密钥形态启发式（宁可误报也不漏报 —— 误报的代价是一条 issue，漏报的代价是泄密）。 */
const SECRET_PATTERNS: readonly RegExp[] = [
  /^sk-[A-Za-z0-9_-]{12,}$/, // OpenAI / DeepSeek / 通义 / Kimi
  /^sk-ant-[A-Za-z0-9_-]{12,}$/, // Anthropic
  /^AIza[A-Za-z0-9_-]{20,}$/, // Google
  /^gh[pousr]_[A-Za-z0-9]{20,}$/, // GitHub
  /^xox[baprs]-[A-Za-z0-9-]{10,}$/, // Slack
  /^Bearer\s+\S{12,}$/i,
  /^[0-9a-f]{32,}$/i, // 32+ 位十六进制（部分自建网关只发一串 hex）
  /^[A-Za-z0-9_-]{40,}$/, // 40+ 位单 token 随机串
]

export function normalizeKeyName(key: string): string {
  return key.toLowerCase().replace(/[_\-.]/g, '')
}

/** 该字符串是否**长得像**明文密钥。 */
export function looksLikeSecret(value: string): boolean {
  const v = value.trim()
  if (!v) return false
  return SECRET_PATTERNS.some((re) => re.test(v))
}

/** 该字段名是否**是**密钥字段（不看值）。 */
export function isSecretKeyName(key: string): boolean {
  return SECRET_KEY_NAMES.includes(normalizeKeyName(key))
}

/**
 * 递归扫描任意结构里的明文密钥。
 *
 * 只扫 `string` 值的**形态**与**字段名**，不做"这个值是不是真 key"的语义判断 ——
 * 领域层没有联网校验的能力，也不该有。
 */
export function scanForSecrets(node: unknown, path = ''): ProfileIssue[] {
  const issues: ProfileIssue[] = []
  if (node === null || node === undefined) return issues

  if (typeof node === 'string') {
    if (looksLikeSecret(node)) {
      issues.push({
        path: path || '<root>',
        code: 'secret_detected',
        message: '检测到明文密钥形态的字符串 —— 凭据只能以引用（authRef）形式出现，绝不进模型配置',
      })
    }
    return issues
  }
  if (typeof node !== 'object') return issues

  if (Array.isArray(node)) {
    node.forEach((item, i) => issues.push(...scanForSecrets(item, `${path}[${i}]`)))
    return issues
  }

  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const here = path ? `${path}.${key}` : key
    if (isSecretKeyName(key)) {
      issues.push({
        path: here,
        code: 'secret_detected',
        message: `字段名「${key}」不允许出现在 ModelProfile 中 —— 请改用 connection.authRef 引用系统凭据库`,
      })
    }
    issues.push(...scanForSecrets(value, here))
  }
  return issues
}

// ---------------------------------------------------------------- 校验

export type IssueCode =
  | 'not_object'
  | 'missing'
  | 'bad_type'
  | 'bad_id'
  | 'empty_provider'
  | 'empty_model'
  | 'empty_name'
  | 'bad_connection_type'
  | 'endpoint_required'
  | 'endpoint_invalid'
  | 'local_path_required'
  | 'auth_ref_invalid'
  | 'secret_detected'
  // ---- 以下由 registry 在"依赖外部状态"时补充（模型层单独校验不出来）----
  | 'provider_unknown'
  | 'provider_disabled'
  | 'duplicate_id'
  | 'unknown_model'

export interface ProfileIssue {
  path: string
  code: IssueCode
  message: string
}

export interface ProfileValidation {
  ok: boolean
  issues: ProfileIssue[]
  /** 校验通过时的**规范化深拷贝**（调用方拿不到原对象，避免外部持有内部引用）。 */
  value?: ModelProfile
}

/** Secret Reference 的形态契约：`pw/<provider>/<slot>`。 */
export const AUTH_REF_PATTERN = /^pw\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/

export function isValidAuthRef(ref: string): boolean {
  return AUTH_REF_PATTERN.test(ref.trim())
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function isHttpEndpoint(v: string): boolean {
  try {
    const u = new URL(v)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

function asBool(v: unknown, fallback: boolean): boolean {
  return typeof v === 'boolean' ? v : fallback
}

/**
 * 校验一个 `ModelProfile`。**失败即整单拒绝**（不产生"半套状态"）。
 *
 * 校验分四段：
 * ① 结构（必填字段与类型）
 * ② 连接（按 `type` 各自必填项 + endpoint 协议）
 * ③ 引用（`authRef` 必须是引用形态，不许是 key）
 * ④ 安全（递归扫密钥，任一命中即拒）
 */
export function validateModelProfile(input: unknown): ProfileValidation {
  const issues: ProfileIssue[] = []

  if (!isPlainObject(input)) {
    return {
      ok: false,
      issues: [{ path: '<root>', code: 'not_object', message: 'ModelProfile 必须是对象' }],
    }
  }

  const str = (key: string, code: IssueCode, required = true): string => {
    const raw = input[key]
    if (raw === undefined || raw === null || (typeof raw === 'string' && !raw.trim())) {
      if (required) {
        issues.push({ path: key, code, message: `缺少必填字段「${key}」` })
      }
      return ''
    }
    if (typeof raw !== 'string') {
      issues.push({ path: key, code: 'bad_type', message: `字段「${key}」必须是字符串` })
      return ''
    }
    return raw.trim()
  }

  const id = str('id', 'missing')
  if (id && !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(id)) {
    issues.push({
      path: 'id',
      code: 'bad_id',
      message: `id 只允许字母/数字/._:- 且以字母数字开头：${id}`,
    })
  }
  const provider = str('provider', 'empty_provider')
  const model = str('model', 'empty_model')
  const name = str('name', 'empty_name')

  // ---- 连接 ----
  const connection = input.connection
  let connType: ConnectionType = 'api'
  if (!isPlainObject(connection)) {
    issues.push({ path: 'connection', code: 'missing', message: '缺少 connection' })
  } else {
    const t = connection.type
    if (typeof t !== 'string' || !CONNECTION_TYPES.includes(t as ConnectionType)) {
      issues.push({
        path: 'connection.type',
        code: 'bad_connection_type',
        message: `connection.type 必须是 ${CONNECTION_TYPES.join(' | ')}，收到 ${JSON.stringify(t)}`,
      })
    } else {
      connType = t as ConnectionType
    }

    const endpoint = typeof connection.endpoint === 'string' ? connection.endpoint.trim() : ''
    const localPath = typeof connection.localPath === 'string' ? connection.localPath.trim() : ''
    const authRef = typeof connection.authRef === 'string' ? connection.authRef.trim() : ''

    if (connType === 'api' || connType === 'agent') {
      if (!endpoint) {
        issues.push({
          path: 'connection.endpoint',
          code: 'endpoint_required',
          message: `connection.type=${connType} 时必须提供 endpoint`,
        })
      } else if (!isHttpEndpoint(endpoint)) {
        issues.push({
          path: 'connection.endpoint',
          code: 'endpoint_invalid',
          message: `endpoint 必须是 http/https 地址：${endpoint}`,
        })
      }
    }
    if (connType === 'local' && !endpoint && !localPath) {
      issues.push({
        path: 'connection.localPath',
        code: 'local_path_required',
        message: 'connection.type=local 时至少要有 endpoint（本地服务地址）或 localPath（权重路径）',
      })
    }
    // 只对 `local` 单独做协议检查 —— `api`/`agent` 上面已经查过，避免同一问题报两条。
    if (connType === 'local' && endpoint && !isHttpEndpoint(endpoint)) {
      issues.push({
        path: 'connection.endpoint',
        code: 'endpoint_invalid',
        message: `endpoint 必须是 http/https 地址：${endpoint}`,
      })
    }
    if (authRef && !isValidAuthRef(authRef)) {
      issues.push({
        path: 'connection.authRef',
        code: 'auth_ref_invalid',
        message: `authRef 必须是 Secret Reference（pw/<provider>/<slot>），收到：${authRef}`,
      })
    }
  }

  // ---- 能力 / 状态 / 元数据 ----
  const capabilities = input.capabilities
  if (capabilities !== undefined) {
    if (!isPlainObject(capabilities)) {
      issues.push({ path: 'capabilities', code: 'bad_type', message: 'capabilities 必须是对象' })
    } else {
      for (const key of CAPABILITY_KEYS) {
        if (capabilities[key] !== undefined && typeof capabilities[key] !== 'boolean') {
          issues.push({
            path: `capabilities.${key}`,
            code: 'bad_type',
            message: `capabilities.${key} 必须是布尔值`,
          })
        }
      }
    }
  }

  const status = input.status
  if (status !== undefined) {
    if (!isPlainObject(status)) {
      issues.push({ path: 'status', code: 'bad_type', message: 'status 必须是对象' })
    } else {
      for (const key of ['enabled', 'available'] as const) {
        if (status[key] !== undefined && typeof status[key] !== 'boolean') {
          issues.push({
            path: `status.${key}`,
            code: 'bad_type',
            message: `status.${key} 必须是布尔值`,
          })
        }
      }
      if (status.lastCheck !== undefined && typeof status.lastCheck !== 'number') {
        issues.push({
          path: 'status.lastCheck',
          code: 'bad_type',
          message: 'status.lastCheck 必须是数字（ms 时间戳）',
        })
      }
    }
  }

  const metadata = input.metadata
  if (metadata !== undefined && !isPlainObject(metadata)) {
    issues.push({ path: 'metadata', code: 'bad_type', message: 'metadata 必须是对象' })
  }

  // ---- 安全：递归扫密钥（放在最后，保证"结构对了才谈安全"不会漏报结构错误）----
  issues.push(...scanForSecrets(input))

  if (issues.length) return { ok: false, issues }

  const srcConn = (connection ?? {}) as Record<string, unknown>
  const srcCap = (capabilities ?? {}) as Record<string, unknown>
  const srcStatus = (status ?? {}) as Record<string, unknown>
  const srcMeta = (metadata ?? {}) as Record<string, unknown>

  const now = Date.now()
  const outConn: ModelConnection = { type: connType }
  if (typeof srcConn.endpoint === 'string') outConn.endpoint = srcConn.endpoint.trim()
  if (typeof srcConn.authRef === 'string') outConn.authRef = srcConn.authRef.trim()
  if (typeof srcConn.localPath === 'string') outConn.localPath = srcConn.localPath.trim()
  if (typeof srcConn.healthPath === 'string') outConn.healthPath = srcConn.healthPath.trim()

  const outStatus: ModelStatus = {
    enabled: asBool(srcStatus.enabled, true),
    available: asBool(srcStatus.available, false),
  }
  if (typeof srcStatus.lastCheck === 'number') outStatus.lastCheck = srcStatus.lastCheck
  if (typeof srcStatus.lastError === 'string') outStatus.lastError = srcStatus.lastError

  const outMeta: ModelMetadata = {
    createdAt: typeof srcMeta.createdAt === 'number' ? srcMeta.createdAt : now,
    updatedAt: typeof srcMeta.updatedAt === 'number' ? srcMeta.updatedAt : now,
  }
  if (isPlainObject(srcMeta.extras)) {
    outMeta.extras = JSON.parse(JSON.stringify(srcMeta.extras)) as Record<string, unknown>
  }

  const value: ModelProfile = {
    id,
    provider,
    name,
    model,
    connection: outConn,
    capabilities: defaultCapabilities({
      chat: asBool(srcCap.chat, true),
      vision: asBool(srcCap.vision, false),
      coding: asBool(srcCap.coding, false),
      agent: asBool(srcCap.agent, false),
    }),
    status: outStatus,
    metadata: outMeta,
  }
  return { ok: true, issues: [], value }
}

/** 密钥掩码（与 Python `CredentialStore.mask` 同规则，保证两侧显示一致）。 */
export function maskOf(secret: string | null | undefined): string {
  if (!secret) return ''
  if (secret.length <= 8) return '*'.repeat(secret.length)
  return `${secret.slice(0, 3)}****${secret.slice(-4)}`
}

/** 校验失败时抛出的错误（供 registry 使用 —— 拒绝必须是"响的"）。 */
export class ModelProfileError extends Error {
  readonly issues: ProfileIssue[]
  constructor(action: string, issues: ProfileIssue[]) {
    const brief = issues
      .slice(0, 4)
      .map((i) => `${i.path}(${i.code})`)
      .join(', ')
    super(`${action} 被拒绝：${brief}${issues.length > 4 ? ` …共 ${issues.length} 条` : ''}`)
    this.name = 'ModelProfileError'
    this.issues = issues
  }
}

/** 校验并返回规范化副本；不通过则抛 `ModelProfileError`。 */
export function assertModelProfile(input: unknown, action = 'ModelProfile 校验'): ModelProfile {
  const res = validateModelProfile(input)
  if (!res.ok || !res.value) throw new ModelProfileError(action, res.issues)
  return res.value
}
