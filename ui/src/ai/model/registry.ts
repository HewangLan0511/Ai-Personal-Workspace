/**
 * AI Model Domain —— Model Registry（TECH-03-A · TASK-03 / TASK-04）
 *
 * ## 它是什么
 * 「模型管理」的**唯一读写口**。UI / AI 助手 / 工作空间 Agent 都从这里取模型、
 * 从这里改默认值，不再各自维护一份 `{provider, model, apiBase}`。
 *
 * ```
 *   L0 能力真相   providers（ProviderRegistry ← Python ai/providers/registry.py）
 *        ↓
 *   本文件        ModelRegistry ── 模型 CRUD + canonical + 订阅
 *        ↓
 *   L1 canonical  core config（ai.provider.current / ai.model.current）
 *   L2 cache      localStorage（ui.ai.provider / ui.ai.model）
 *   Secret        authRef → 系统凭据库（只存引用，不存明文）
 * ```
 *
 * ## 为什么 canonical 只有一个（TASK-03 的答案）
 * 现状有**五处**来源（PW-INTEGRATION-003 §3.1 实测）：localStorage、core config 同名键副本、
 * 模式 `aiProfile`、`ai.default_provider`、请求级参数。收口后：
 *
 * | 来源 | 去向 | 理由 |
 * |------|------|------|
 * | L1 `ai.provider.current` / `ai.model.current` | **唯一事实来源** | 冻结契约指定 |
 * | L2 `localStorage ui.ai.*` | **降级缓存**（非真相） | core 不可达时的启动兜底 |
 * | core 过渡镜像 `ui.ai.provider` / `ui.ai.model` | **保留 + 标记 `pendingSync`** | L1 键尚未在 core 登记，先落已登记的键，避免写入失败 |
 * | 模式 `aiProfile` | **保留为建议层**（L3） | 设计期意图，需用户确认才改 L1 |
 * | `ai.default_provider` | **保留为无 UI 调用者回退**（L4） | 插件 / 外部 Agent 的合法通道 |
 * | 请求级 `AiChatArgs.provider` | **保留为传输参数**（L5，只传不决策） | 程序化调用自负 |
 *
 * 「逐步废弃」清单见 `docs/tech/model-management-runtime.md` §4。
 *
 * ## 零接线（本轮刻意）
 * 本文件**没有被任何页面 import** —— 因为执行原则 2 要求"不替换已有模型来源"。
 * 所以它是**并行新增的一层**：能力齐备、可被验收脚本直接驱动，
 * 但不改变 `stores/ai.ts` 现在的行为。接线属于 TECH-03-B。
 *
 * ## 框架无关
 * 不 import Vue / `@/`。IO 全部经 `RegistryPorts` 注入，
 * 因此可以在 Node 里直接编译执行（verify_model_registry.py T1~T5）。
 */

import {
  ModelProfileError,
  assertModelProfile,
  draftModelProfile,
  type ConnectionType,
  type ModelProfile,
  type ModelProfileInput,
} from './model'
import {
  ProviderRegistry,
  type ConnectionTestResult,
  type ModelDescriptor,
  type ModelIo,
  type ProviderDescriptor,
  type ProviderDescriptorInput,
} from './provider'
import {
  materializeArchiveRecord,
  parseArchive,
  serializeArchive,
  type ArchiveIssue,
} from './archive'

// ---------------------------------------------------------------- 端口（注入的 IO）

export interface CanonicalValues {
  provider: string
  model: string
  apiBase: string
}

/** `source` 说明「这次是从哪读到的」；`none` = 哪都没有。 */
export type CanonicalSource = 'core' | 'mirror' | 'cache' | 'none'

/** 写入真正落到了哪里：L1 键 / core 过渡镜像键 / 仅缓存。 */
export type CanonicalLanding = 'core' | 'mirror' | 'cache' | 'none'

export interface CanonicalRead {
  values: CanonicalValues
  from: Exclude<CanonicalSource, 'none'>
}

export interface CanonicalPort {
  /** 冻结契约的 L1 键名（默认 `ai.provider.current` / `ai.model.current`）。 */
  readonly keys: { provider: string; model: string }
  /**
   * 过渡镜像键名（core 里**已登记**的旧键）。
   * L1 键还没登记时写它会直接 bail —— 所以镜像键是"先落得住"的那一层。
   */
  readonly mirrorKeys: { provider: string; model: string }
  read(): Promise<CanonicalRead | null>
  write(patch: Partial<CanonicalValues>): Promise<{ landedOn: CanonicalLanding }>
}

export interface CachePort {
  read(): CanonicalValues | null
  write(values: CanonicalValues): void
  clear(): void
}

export interface SecretPort {
  has(providerId: string): Promise<boolean>
  /** 写入凭据。**返回值只有掩码，绝不含明文**。 */
  set(
    providerId: string,
    secret: string,
  ): Promise<{ provider: string; ref: string; mask: string; backend: string }>
  remove(providerId: string): Promise<boolean>
  /** 生成 Secret Reference（纯字符串运算，不触达凭据库）。 */
  refFor(providerId: string): string
}

export interface CapabilityPort {
  /** L0：系统当前有哪些 Provider（只读投影）。 */
  loadProviders(): Promise<ProviderDescriptorInput[]>
  /** 哪些 Provider 已配好凭据（**只问有无，不问值**）。 */
  loadSecretPresence(): Promise<string[]>
}

/**
 * 模型清单归档端口（TECH-06-B Part 1）。
 *
 * 交换的是**归档串**（形态由 `ai/model/archive.ts` 唯一定义，键 `ai.models.registry`），
 * 端口本身只是"读一个串 / 写一个串" —— 这样归档格式可以被 Node 直接穷举，
 * 而存储实现（core config）保持哑。
 *
 * **谁读谁写只有 `ModelRegistry`**：`hydrate()` 读、`add/update/remove/clear` 写。
 * 页面与 AI 侧栏不接触本端口 —— 指令禁止的「页面自己存模型 / UI 绕过 Registry」
 * 在结构上不可能发生。
 */
export interface ArchivePort {
  /** 契约登记的键名（仅供排障/验收展示，不参与判断）。 */
  readonly key: string
  /**
   * 读归档串。空串 = 从未写过。
   * **抛错 = 存储不可达** —— Registry 据此进入 fail-closed（拒绝覆盖写），
   * 绝不把"读不到"当成"没有模型"写回空清单。
   */
  read(): Promise<string>
  /** 写归档串。失败**不抛给调用方**（落盘是异步旁路），错误记在归档状态里。 */
  write(raw: string): Promise<void>
}

export interface RegistryPorts {
  io: ModelIo
  capability: CapabilityPort
  canonical: CanonicalPort
  cache: CachePort
  secret: SecretPort
  /**
   * **可选**：模型清单归档。缺省 = 不持久化（单测 / 纯浏览器桩）。
   * 生产组合根 `createCoreModelRegistry()` 必须注入 —— 漏注入会静默退化为内存态，
   * 故验收脚本有专门的"接线检索"断言（verify_tech06b T1c）。
   */
  archive?: ArchivePort
  now?: () => number
}

// ---------------------------------------------------------------- 对外的读模型

export type ModelEntryStatus = 'ready' | 'unchecked' | 'unavailable' | 'disabled'

/**
 * UI 列表项（TASK-04 `models.list()` 的返回元素）。
 * 比 `ModelProfile` 更"UI 友好"：状态已归约、默认标记已算好、凭据只暴露布尔。
 */
export interface ModelListEntry {
  id: string
  name: string
  provider: string
  model: string
  connectionType: ConnectionType
  status: ModelEntryStatus
  capabilities: ModelProfile['capabilities']
  isDefault: boolean
  hasSecret: boolean
  enabled: boolean
  /**
   * 该 Provider 是否需要 API Key（本地模型为 `false`）。
   *
   * TECH-06-A 新增（加法）：UI 要区分「未配置」与「连接失败」，
   * 缺了这条就无法判断"失败是因为压根没凭据"。
   */
  needsSecret: boolean
  /**
   * 最近一次探测的失败码（成功或无记录 = 空串）。
   *
   * TECH-06-A 新增（加法）：没有它，UI 只能显示一个笼统的「不可用」——
   * 「离线」（服务没起）与「连接失败」（鉴权/超时）就分不开（见 `status.ts`）。
   */
  lastError: string
  /** 最近一次探测时间（ms；`0` = 从未探测）。 */
  lastCheck: number
}

export interface CanonicalSnapshot extends CanonicalValues {
  source: CanonicalSource
  /** `true` = 本次读取的真身不在 L1（core 不可达 / 键未登记）—— UI 应提示"离线态"。 */
  stale: boolean
  /** `true` = **最近一次写入**未落到 L1（落了过渡镜像或仅缓存），待迁移。 */
  pendingSync: boolean
}

export interface DefaultModelView {
  canonical: CanonicalSnapshot
  /** canonical 指向的模型在注册表里的实体；找不到则为 `null`。 */
  profile: ModelProfile | null
  /** canonical 有值但注册表里没有对应 profile —— 典型原因：模型被删了。 */
  dangling: boolean
  /** canonical 从未设置过。 */
  unset: boolean
}

export interface HydrateReport {
  providers: number
  secrets: number
  models: number
  canonical: CanonicalSnapshot
  /** 归档层结果（TECH-06-B）。`state='absent'` = 端口未注入（不持久化）。 */
  archive: ArchiveState
}

/** 归档层状态（如实暴露，不谎报"已持久化"）。 */
export interface ArchiveState {
  /** `absent` = 未注入端口；`ok` = 读到过（可写）；`unreadable` = 读失败（**拒绝覆盖写**）。 */
  state: 'absent' | 'ok' | 'unreadable'
  /** 本次 hydrate 从归档恢复出的模型数。 */
  restored: number
  /** 解析 / 恢复阶段的问题清单（坏记录逐条丢弃，不抛错）。 */
  issues: ArchiveIssue[]
  /** 最近一次**写**失败的原文（空串 = 没失败过 / 还没写过）。 */
  writeError: string
}

export interface RegistryMutation {
  revision: number
  reason: string
}

// ---------------------------------------------------------------- 纯工具

/** capability 键（L0 的 `capabilities`）→ 能力声明。显式声明永远优先。 */
export function capabilitiesFromProvider(
  providerKeys: readonly string[],
  explicit?: Partial<ModelProfile['capabilities']>,
): Partial<ModelProfile['capabilities']> {
  const keys = new Set(providerKeys.map((k) => k.toLowerCase()))
  const derived: Partial<ModelProfile['capabilities']> = {
    chat: keys.has('chat') || keys.has('stream'),
    // L0 不声明 vision / coding —— 不猜（猜出来的能力会让 UI 给出错误承诺）
    vision: false,
    coding: false,
    // agent 能力由连接类型单独判定，见 add()
    agent: false,
  }
  return { ...derived, ...(explicit ?? {}) }
}

/** 把 profile 的可用性归约成 UI 状态。 */
export function entryStatusOf(p: ModelProfile): ModelEntryStatus {
  if (!p.status.enabled) return 'disabled'
  if (p.status.lastError) return 'unavailable'
  if (p.status.available) return 'ready'
  return 'unchecked'
}

// ---------------------------------------------------------------- ModelRegistry

/**
 * 模型注册表。**唯一读写口**（TASK-03 的"单一事实来源"落点）。
 *
 * 生命周期：
 * ```
 * const reg = new ModelRegistry(ports)   // 构造（不碰 IO）
 * await reg.hydrate()                    // 读 L0 → 读 L1 → 落在内存
 * reg.models.list()                      // 纯读，同步
 * await reg.models.check(id)             // 唯一会发请求的动作
 * ```
 */
export class ModelRegistry {
  readonly providers: ProviderRegistry

  private readonly ports: RegistryPorts
  private readonly now: () => number

  private readonly store = new Map<string, ModelProfile>()
  /** 本会话内被**显式**设为默认的 profile id（持久化真相仍是 canonical）。 */
  private explicitDefaultId: string | null = null
  private secrets = new Set<string>()
  private canonical: CanonicalSnapshot = {
    provider: '',
    model: '',
    apiBase: '',
    source: 'none',
    stale: true,
    pendingSync: false,
  }

  private listeners = new Set<(m: RegistryMutation) => void>()
  private revision = 0
  private hydrated = false

  // ---- 归档（TECH-06-B Part 1）--------------------------------------
  /** 只有**成功读到过**归档才允许覆盖写 —— 读不到就写 = 静默清库，绝不发生。 */
  private archiveState: ArchiveState = {
    state: 'absent',
    restored: 0,
    issues: [],
    writeError: '',
  }
  /** 串行落盘队列：保证"最后一次变更的最终状态"一定赢（并发 add/remove 不乱序）。 */
  private persistChain: Promise<void> = Promise.resolve()

  constructor(ports: RegistryPorts, providers?: ProviderRegistry) {
    this.ports = ports
    this.providers = providers ?? new ProviderRegistry()
    this.now = ports.now ?? (() => Date.now())
  }

  // ---- 订阅 ---------------------------------------------------------

  subscribe(fn: (m: RegistryMutation) => void): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  getRevision(): number {
    return this.revision
  }

  private notify(reason: string): void {
    this.revision += 1
    const info: RegistryMutation = { revision: this.revision, reason }
    for (const fn of Array.from(this.listeners)) {
      try {
        fn(info)
      } catch {
        /* 单个订阅者抛错不影响其余 */
      }
    }
  }

  // ---- 装载（L0 + L1 + Secret 存在性） -------------------------------

  /**
   * 装载 L0 能力真相 + **归档（模型清单）** + 解析 canonical。
   * **幂等**：重复调用会重新投影 Provider（覆盖式），并从 L1 重读 canonical。
   *
   * 归档装载顺序刻意在 Provider **之后**：恢复出的模型不依赖 Provider 在册
   * （`materializeArchiveRecord` 只做结构校验），但这样日志里能对上"恢复 N 条、其中
   * M 条 Provider 当前未知"。
   */
  async hydrate(): Promise<HydrateReport> {
    let providers: ProviderDescriptorInput[] = []
    try {
      providers = await this.ports.capability.loadProviders()
    } catch {
      providers = [] // core 不可达 → 空能力面，调用方据 `providers===0` 判断
    }
    for (const p of providers) this.providers.registerProvider(p)

    let secretIds: string[] = []
    try {
      secretIds = await this.ports.capability.loadSecretPresence()
    } catch {
      secretIds = []
    }
    this.secrets = new Set(secretIds.map((s) => s.toLowerCase()))

    const archive = await this.loadArchive()
    this.archiveState = archive
    this.canonical = await this.readCanonical()
    this.hydrated = true
    this.notify('hydrate')
    return {
      providers: providers.length,
      secrets: this.secrets.size,
      models: this.store.size,
      canonical: { ...this.canonical },
      archive: { ...archive, issues: [...archive.issues] },
    }
  }

  /**
   * 读归档并**恢复**到内存。**读失败不等于没有模型** —— 状态如实置 `unreadable`，
   * 并让 `scheduleArchivePersist()` 从此拒绝写（fail-closed）。
   */
  private async loadArchive(): Promise<ArchiveState> {
    const port = this.ports.archive
    if (!port) {
      return { state: 'absent', restored: 0, issues: [], writeError: '' }
    }
    let raw: string
    try {
      raw = await port.read()
    } catch (err) {
      return {
        state: 'unreadable',
        restored: 0,
        issues: [
          {
            at: '<read>',
            message: `读不到既有模型清单（${String(err)}）—— 本会话禁止覆盖写，避免清库`,
          },
        ],
        writeError: '',
      }
    }
    const parsed = parseArchive(raw)
    let restored = 0
    for (const rec of parsed.models) {
      const m = materializeArchiveRecord(rec, this.now())
      if (m.error || !m.profile) {
        parsed.issues.push({ at: rec.id, message: m.error ?? '未通过结构校验' })
        continue
      }
      this.store.set(m.profile.id, m.profile)
      restored += 1
    }
    return { state: 'ok', restored, issues: parsed.issues, writeError: '' }
  }

  /** 归档层当前状态（UI / 验收可读，**只读**）。 */
  getArchiveState(): ArchiveState {
    return { ...this.archiveState, issues: [...this.archiveState.issues] }
  }

  /** 归档键（未注入端口时为 `null`）。 */
  archiveKey(): string | null {
    return this.ports.archive?.key ?? null
  }

  /** 等待所有挂起的落盘完成（测试 / 退出前调用）。 */
  async archiveFlushed(): Promise<void> {
    await this.persistChain
  }

  /**
   * 把**当前完整清单**排进落盘队列。fire-and-forget：
   * `add/update/remove` 保持同步签名（指令要求不破坏 ModelRegistry），
   * 真正的写入串行执行、最后一次状态必胜；失败只记 `writeError`，不影响调用方。
   */
  private scheduleArchivePersist(): void {
    const port = this.ports.archive
    if (!port || this.archiveState.state !== 'ok') return
    const raw = serializeArchive([...this.store.values()])
    this.persistChain = this.persistChain
      .then(() => port.write(raw))
      .then(() => {
        this.archiveState = { ...this.archiveState, writeError: '' }
      })
      .catch((err) => {
        this.archiveState = { ...this.archiveState, writeError: String(err) }
      })
  }

  isHydrated(): boolean {
    return this.hydrated
  }

  private async safeReadCanonical(): Promise<CanonicalRead | null> {
    try {
      return await this.ports.canonical.read()
    } catch {
      return null // L1 读失败（core 不可达）→ 交给 L2 兜底
    }
  }

  /** 读 canonical：L1 → L2。**不写**任何东西。 */
  private async readCanonical(): Promise<CanonicalSnapshot> {
    const l2 = this.ports.cache.read()
    const l1 = await this.safeReadCanonical()
    const hasL1 = !!l1 && !!(l1.values.provider || l1.values.model)
    if (hasL1 && l1) {
      return {
        ...l1.values,
        // apiBase 没有 core 键（见 ports.ts 说明）→ 只能从 L2 补
        apiBase: l1.values.apiBase || l2?.apiBase || '',
        source: l1.from === 'core' ? 'core' : 'mirror',
        stale: false,
        pendingSync: l1.from !== 'core', // 读的是过渡镜像 → 还没算真正落到 L1
      }
    }
    if (l2 && (l2.provider || l2.model)) {
      return { ...l2, source: 'cache', stale: true, pendingSync: false }
    }
    return { provider: '', model: '', apiBase: '', source: 'none', stale: true, pendingSync: false }
  }

  // ---- canonical 读写（TASK-03） ------------------------------------

  getCanonical(): CanonicalSnapshot {
    return { ...this.canonical }
  }

  /**
   * 写 canonical（**唯一写口**）。
   *
   * 契约（PW-INTEGRATION-003 §3.4）：
   * - canonical 不得指向**未注册**或 `enabled=false` 的 Provider —— 直接拒绝，不静默兜底；
   * - 写序：L1 → （失败则）core 过渡镜像 → L2 缓存；
   * - 结果如实回报 `source` / `stale` / `pendingSync`，**不谎报"已落库"**。
   */
  async setCanonical(patch: Partial<CanonicalValues>): Promise<CanonicalSnapshot> {
    const next: CanonicalValues = {
      provider: (patch.provider ?? this.canonical.provider).trim(),
      model: (patch.model ?? this.canonical.model).trim(),
      apiBase: (patch.apiBase ?? this.canonical.apiBase).trim(),
    }

    if (next.provider) {
      const d = this.providers.getProvider(next.provider)
      if (!d) {
        throw new ModelProfileError('setCanonical', [
          {
            path: 'provider',
            code: 'provider_unknown',
            message: `canonical 不得指向未注册的 Provider：${next.provider}`,
          },
        ])
      }
      if (!d.enabled) {
        throw new ModelProfileError('setCanonical', [
          {
            path: 'provider',
            code: 'provider_disabled',
            message: `canonical 不得指向未开放的 Provider：${next.provider}`,
          },
        ])
      }
    }

    let landedOn: CanonicalLanding = 'none'
    try {
      const wr = await this.ports.canonical.write({
        provider: next.provider,
        model: next.model,
      })
      landedOn = wr.landedOn
    } catch {
      landedOn = 'none'
    }
    if (landedOn !== 'core') {
      // L1 没落住 → 至少保证缓存里有，供下次启动兜底
      this.ports.cache.write(next)
    }

    this.canonical = {
      ...next,
      source: landedOn === 'core' ? 'core' : landedOn === 'mirror' ? 'mirror' : 'cache',
      stale: landedOn === 'none' || landedOn === 'cache',
      pendingSync: landedOn !== 'core',
    }
    this.notify('canonical')
    return { ...this.canonical }
  }

  /** 刷新 canonical（例如收到 core 的 `CONFIG_CHANGED` 之后）。 */
  async refreshCanonical(): Promise<CanonicalSnapshot> {
    this.canonical = await this.readCanonical()
    this.notify('canonical-refresh')
    return { ...this.canonical }
  }

  // ---- 模型 CRUD（TASK-04 / T1~T3） ---------------------------------

  /** 全部模型（含禁用）；`onlyEnabled` 只取启用中的。 */
  list(opts: { onlyEnabled?: boolean } = {}): ModelListEntry[] {
    const out: ModelListEntry[] = []
    for (const p of this.store.values()) {
      if (opts.onlyEnabled && !p.status.enabled) continue
      out.push({
        id: p.id,
        name: p.name,
        provider: p.provider,
        model: p.model,
        connectionType: p.connection.type,
        status: entryStatusOf(p),
        capabilities: { ...p.capabilities },
        isDefault: this.isDefault(p),
        hasSecret: this.hasCredential(p.provider),
        enabled: p.status.enabled,
        // TECH-06-A：把"为什么是这个状态"的证据一并透出 —— 否则 UI 只能显示一个笼统词。
        // `needsKey` 取自 L0 的能力真相（ProviderDescriptor），不猜；
        // L0 不可用（拿不到 Provider 描述）时按连接类型保守回退：API 模型默认需要凭据。
        needsSecret: (() => {
          const desc = this.providers.getProvider(p.provider)
          return desc ? desc.needsKey : p.connection.type === 'api'
        })(),
        lastError: p.status.lastError ?? '',
        lastCheck: p.status.lastCheck ?? 0,
      })
    }
    return out.sort((a, b) => a.id.localeCompare(b.id))
  }

  get(id: string): ModelProfile | null {
    const p = this.store.get(id.trim())
    return p ? cloneProfile(p) : null
  }

  size(): number {
    return this.store.size
  }

  private isDefault(p: ModelProfile): boolean {
    if (this.explicitDefaultId) return this.explicitDefaultId === p.id
    // 尚未在本会话显式设过 → 由 canonical（持久化的用户意图）推导
    if (!this.canonical.provider) return false
    return this.canonical.provider === p.provider && this.canonical.model === p.model
  }

  /**
   * 创建模型（T1）。
   *
   * 缺省填充规则（让"新增模型"不必知道内部细节）：
   * - `connection.type` ← Provider 的 `connectionType`
   * - `connection.endpoint` ← Provider 的 `defaultEndpoint`
   * - `connection.authRef` ← `secret.refFor(provider)`（**只写引用**，不碰密钥）
   * - `capabilities` ← L0 声明的能力键（显式声明优先）
   */
  add(input: ModelProfileInput): ModelProfile {
    const providerId = String(input.provider ?? '').trim().toLowerCase()
    // 结构错误先于「依赖外部状态」的错误报出来 —— 空 provider 应报 empty_provider，
    // 而不是先拿空串去查表再报一个含糊的 provider_unknown。
    if (!providerId) {
      throw new ModelProfileError('add', [
        { path: 'provider', code: 'empty_provider', message: 'provider 不能为空' },
      ])
    }
    if (!String(input.model ?? '').trim()) {
      throw new ModelProfileError('add', [
        { path: 'model', code: 'empty_model', message: 'model 不能为空' },
      ])
    }
    const d = this.providers.getProvider(providerId)
    if (!d) {
      throw new ModelProfileError('add', [
        {
          path: 'provider',
          code: 'provider_unknown',
          message: `Provider 未注册：${providerId}（可用：${this.providers
            .listProviders()
            .map((x) => x.id)
            .join(', ')}）`,
        },
      ])
    }
    if (!d.enabled) {
      throw new ModelProfileError('add', [
        {
          path: 'provider',
          code: 'provider_disabled',
          message: `Provider 尚未开放：${providerId}。${d.note}`,
        },
      ])
    }

    const caps = capabilitiesFromProvider(d.capabilities, input.capabilities)
    const draft = draftModelProfile(
      // 顺序有讲究：Provider 的连接类型作默认，`input` 的显式声明可以覆盖它
      { connectionType: d.connectionType, ...input, provider: providerId },
      this.now(),
    )
    // 补缺省（只在调用方没给的时候填 —— 显式给的一律尊重）
    if (!draft.connection.endpoint && d.defaultEndpoint) {
      draft.connection.endpoint = d.defaultEndpoint
    }
    if (d.needsKey && !draft.connection.authRef) {
      draft.connection.authRef = this.ports.secret.refFor(providerId)
    }
    draft.capabilities = {
      ...draft.capabilities,
      chat: caps.chat ?? draft.capabilities.chat,
      vision: caps.vision ?? draft.capabilities.vision,
      coding: caps.coding ?? draft.capabilities.coding,
      agent: d.connectionType === 'agent' ? true : (caps.agent ?? draft.capabilities.agent),
    }

    const value = assertModelProfile(draft, '新增模型')
    if (this.store.has(value.id)) {
      throw new ModelProfileError('add', [
        {
          path: 'id',
          code: 'duplicate_id',
          message: `模型 id 已存在：${value.id}（同一 Provider 同一个模型只登记一次）`,
        },
      ])
    }
    this.store.set(value.id, value)
    this.notify(`add:${value.id}`)
    this.scheduleArchivePersist()
    return cloneProfile(value)
  }

  /** 局部更新（改名称/模型/能力/启用状态）。改的是默认模型时同步 canonical。 */
  update(id: string, patch: Partial<ModelProfileInput>): ModelProfile {
    const cur = this.store.get(id.trim())
    if (!cur) {
      throw new ModelProfileError('update', [
        { path: 'id', code: 'unknown_model', message: `模型不存在：${id}` },
      ])
    }
    const wasDefault = this.isDefault(cur)
    const merged = draftModelProfile(
      {
        id: cur.id,
        provider: patch.provider ?? cur.provider,
        name: patch.name ?? cur.name,
        model: patch.model ?? cur.model,
        connectionType: patch.connectionType ?? cur.connection.type,
        connection: { ...cur.connection, ...(patch.connection ?? {}) },
        capabilities: { ...cur.capabilities, ...(patch.capabilities ?? {}) },
        status: { ...cur.status, ...(patch.status ?? {}) },
        extras: patch.extras ?? cur.metadata.extras,
      },
      this.now(),
    )
    merged.metadata.createdAt = cur.metadata.createdAt
    merged.metadata.updatedAt = this.now()

    const value = assertModelProfile(merged, '更新模型')
    if (value.id !== cur.id && this.store.has(value.id)) {
      throw new ModelProfileError('update', [
        { path: 'id', code: 'duplicate_id', message: `目标 id 已被占用：${value.id}` },
      ])
    }
    this.store.delete(cur.id)
    this.store.set(value.id, value)
    if (wasDefault) this.explicitDefaultId = value.id
    this.notify(`update:${value.id}`)
    this.scheduleArchivePersist()
    return cloneProfile(value)
  }

  /**
   * 删除模型（T3）。
   *
   * 两条刻意保留：
   * - **不动 canonical** —— 删掉一个模型不该顺手清掉用户在 AI 助手里的 Provider 选择；
   *   删的若是默认项，canonical 会进入 `dangling` 状态（`getDefault()` 会如实报告）。
   * - **不动凭据** —— 凭据是 Provider 级的（`pw/<provider>/default`），
   *   同 Provider 的其它模型还要用。
   */
  remove(id: string): boolean {
    const key = id.trim()
    const existed = this.store.delete(key)
    if (existed) {
      if (this.explicitDefaultId === key) this.explicitDefaultId = null
      this.notify(`remove:${key}`)
      // 落盘发生在"确实删了"之后 —— 没删成功（返回 false）不产生一次无意义写
      this.scheduleArchivePersist()
    }
    return existed
  }

  /** 清空（测试/重置用；不触达 L1 与凭据）。归档会同步写成空清单 —— 与内存一致。 */
  clear(): void {
    this.store.clear()
    this.explicitDefaultId = null
    this.notify('clear')
    this.scheduleArchivePersist()
  }

  // ---- 默认模型（TASK-04 / T2） -------------------------------------

  /** 设默认模型：**写 canonical**（唯一事实来源），而不是另存一个 default 字段。 */
  async setDefault(id: string): Promise<DefaultModelView> {
    const p = this.store.get(id.trim())
    if (!p) {
      throw new ModelProfileError('setDefault', [
        { path: 'id', code: 'unknown_model', message: `模型不存在：${id}` },
      ])
    }
    this.explicitDefaultId = p.id
    await this.setCanonical({
      provider: p.provider,
      model: p.model,
      apiBase: p.connection.endpoint ?? this.canonical.apiBase,
    })
    return this.getDefault()
  }

  getDefault(): DefaultModelView {
    const c = this.getCanonical()
    const profile =
      this.explicitDefaultId && this.store.has(this.explicitDefaultId)
        ? this.store.get(this.explicitDefaultId)!
        : (this.findByCanonical() ?? null)
    const unset = !c.provider && !c.model
    return {
      canonical: c,
      profile: profile ? cloneProfile(profile) : null,
      dangling: !unset && !profile,
      unset,
    }
  }

  private findByCanonical(): ModelProfile | null {
    for (const p of this.store.values()) {
      if (p.provider === this.canonical.provider && p.model === this.canonical.model) return p
    }
    return null
  }

  // ---- 测试与发现（TASK-02 / TASK-04 `check`） ----------------------

  /**
   * 测试模型连通性。**唯一会发请求的方法。**
   * 结果写回 `profile.status`（`available` / `lastCheck` / `lastError`）。
   * 未知模型不抛错，返回 `not_implemented` 结果（与 `ProviderRegistry` 对称）。
   */
  async check(id: string): Promise<ConnectionTestResult> {
    const p = this.store.get(id.trim())
    if (!p) {
      const stub: ProviderDescriptor = {
        id: id.trim(),
        label: id.trim(),
        connectionType: 'api',
        defaultEndpoint: '',
        defaultModel: '',
        needsKey: false,
        enabled: true,
        note: '',
        capabilities: [],
      }
      return {
        provider: stub.id,
        ok: false,
        code: 'not_implemented',
        message: `未注册的模型：${id}`,
        modelCount: 0,
        ms: 0,
        checkedAt: this.now(),
        probed: false,
      }
    }
    const res = await this.providers.testConnection(p.provider, this.ports.io, {
      apiBase: p.connection.endpoint,
      model: p.model,
      hasSecret: this.hasCredential(p.provider),
    })
    p.status.available = res.ok
    p.status.lastCheck = res.checkedAt
    if (res.ok) delete p.status.lastError
    else p.status.lastError = res.code
    p.metadata.updatedAt = this.now()
    this.notify(`check:${p.id}`)
    return res
  }

  /** 某 Provider 的可用模型（供"新增模型"下拉）。列表语义 → 不抛错。 */
  async providerModels(
    providerId: string,
    ctx: { apiBase?: string; model?: string } = {},
  ): Promise<ModelDescriptor[]> {
    return this.providers.getModels(providerId, this.ports.io, {
      ...ctx,
      hasSecret: this.hasCredential(providerId),
    })
  }

  listProviders(opts: { enabledOnly?: boolean } = {}): ProviderDescriptor[] {
    return this.providers.listProviders(opts)
  }

  // ---- 凭据（TASK-06） ---------------------------------------------

  /** 该 Provider 是否已配凭据（**只回布尔**）。本地/Agent 恒为 `true`（不需要 key）。 */
  hasCredential(providerId: string): boolean {
    const d = this.providers.getProvider(providerId)
    if (d && !d.needsKey) return true
    return this.secrets.has(providerId.trim().toLowerCase())
  }

  /** 生成某个 Provider 的 Secret Reference（给 UI 展示用）。 */
  credentialRef(providerId: string): string {
    return this.ports.secret.refFor(providerId)
  }

  /**
   * 写入凭据。**返回值只有掩码** —— 明文不进 UI state、不进模型配置、不进日志。
   * 模型侧永远只见 `connection.authRef`（引用）。
   */
  async setCredential(
    providerId: string,
    secret: string,
  ): Promise<{ provider: string; ref: string; mask: string; backend: string }> {
    if (!this.providers.has(providerId)) {
      throw new ModelProfileError('setCredential', [
        {
          path: 'provider',
          code: 'provider_unknown',
          message: `Provider 未注册：${providerId}`,
        },
      ])
    }
    const res = await this.ports.secret.set(providerId.trim().toLowerCase(), secret)
    this.secrets.add(providerId.trim().toLowerCase())
    this.notify(`credential:${providerId}`)
    return res
  }

  async removeCredential(providerId: string): Promise<boolean> {
    const removed = await this.ports.secret.remove(providerId)
    this.secrets.delete(providerId.trim().toLowerCase())
    this.notify(`credential-remove:${providerId}`)
    return removed
  }

  // ---- 存储快照（持久化扩展点，本轮不接线） -------------------------

  /**
   * 导出全部模型为可序列化结构。
   *
   * ⚠️ 输出**必然不含密钥**（领域模型里根本没有密钥字段）。
   * 本轮不落库（执行原则 2：不迁移数据库）；这是给 TECH-03-B 预留的持久化形状。
   */
  exportProfiles(): ModelProfile[] {
    return [...this.store.values()].map(cloneProfile)
  }

  /** 从快照恢复（校验失败整体抛错，不做部分导入）。 */
  importProfiles(list: readonly unknown[]): ModelProfile[] {
    const values = list.map((raw) => assertModelProfile(raw, '导入模型'))
    for (const v of values) {
      if (!this.providers.has(v.provider)) {
        throw new ModelProfileError('importProfiles', [
          {
            path: v.id,
            code: 'provider_unknown',
            message: `Provider 未注册：${v.provider}`,
          },
        ])
      }
    }
    for (const v of values) this.store.set(v.id, v)
    this.notify('import')
    return values.map(cloneProfile)
  }
}

// ---------------------------------------------------------------- 工具

function cloneProfile(p: ModelProfile): ModelProfile {
  return {
    ...p,
    connection: { ...p.connection },
    capabilities: { ...p.capabilities },
    status: { ...p.status },
    metadata: {
      ...p.metadata,
      ...(p.metadata.extras ? { extras: { ...p.metadata.extras } } : {}),
    },
  }
}

/** TASK-04 的 `models.*` 门面 —— 给 UI Skill 用的**窄接口**。 */
export interface ModelsApi {
  /** 全部模型（含状态/默认标记/是否有凭据）。 */
  list(opts?: { onlyEnabled?: boolean }): ModelListEntry[]
  get(id: string): ModelProfile | null
  /** 新增模型。 */
  add(input: ModelProfileInput): ModelProfile
  update(id: string, patch: Partial<ModelProfileInput>): ModelProfile
  /** 删除模型。 */
  remove(id: string): boolean
  /** 设默认模型（写 canonical）。 */
  setDefault(id: string): Promise<DefaultModelView>
  getDefault(): DefaultModelView
  /** 测试模型连通性。 */
  check(id: string): Promise<ConnectionTestResult>
}

/** 从 Registry 取出窄接口（UI 只需 `models.list()` 这类调用）。 */
export function createModelsApi(registry: ModelRegistry): ModelsApi {
  return {
    list: (opts) => registry.list(opts),
    get: (id) => registry.get(id),
    add: (input) => registry.add(input),
    update: (id, patch) => registry.update(id, patch),
    remove: (id) => registry.remove(id),
    setDefault: (id) => registry.setDefault(id),
    getDefault: () => registry.getDefault(),
    check: (id) => registry.check(id),
  }
}

export { ModelProfileError }
export type { ModelProfile, ModelProfileInput }
