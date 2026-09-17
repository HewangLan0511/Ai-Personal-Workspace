/**
 * AI Model Domain —— IO 适配器（TECH-03-A · 端口的生产实现）
 *
 * ## 为什么单独一个文件
 * 领域层（`model.ts` / `provider.ts` / `registry.ts`）**零外部依赖** ——
 * 这样它能在 Node 里被直接编译执行，验收脚本 T1~T5 就是这么跑的。
 * 凡是要碰 core / localStorage / 凭据库的，全部集中在本文件。
 *
 * ```
 * registry.ts ──依赖──> 端口接口（CapabilityPort / CanonicalPort / CachePort / SecretPort / ModelIo）
 *                              ↑ 实现
 *                        本文件（唯一 import @/api 的地方）
 * ```
 *
 * ## 复用既有能力，零新增后端
 * | 端口 | 用的既有 command | 备注 |
 * |------|------------------|------|
 * | capability | `ai_info` | L0 能力真相（Python `registry.available()`） |
 * | modelIo | `ai_list_models` | 拉模型列表，已是既有能力 |
 * | secret | `ai_set_credential` / `ai_delete_credential` | 只进系统凭据库，只回掩码 |
 * | canonical | `get_config` / `put_config` | L1 键 + 过渡镜像键 |
 * | cache | `localStorage` | L2，键与 `stores/ai.ts` 完全一致 |
 * | archive | `get_config` / `put_config` | TECH-06-B：模型清单（键 `ai.models.registry`，契约 v13） |
 *
 * **没有新增任何 core 命令、没有数据库改动**。config 键 `ai.models.registry` 是
 * TECH-06-B 唯一登记的新键（此前 "没有新增任何 config 键" 的说法自本轮起不再成立，显式改写）。
 * 这仍是"新接口包裹旧逻辑"的字面执行 —— 命令、通道、表全部复用。
 */

import { inTauri, invokeCore } from '@/api/client'
import { logger } from '@/utils/logger'

import { maskOf, type ModelProfile } from './model'
import { ARCHIVE_KEY } from './archive'
import type {
  ModelDescriptor,
  ModelIo,
  ProviderDescriptorInput,
} from './provider'
import {
  ModelRegistry,
  type ArchivePort,
  type CachePort,
  type CanonicalLanding,
  type CanonicalPort,
  type CanonicalRead,
  type CanonicalValues,
  type CapabilityPort,
  type RegistryPorts,
  type SecretPort,
} from './registry'

// ---------------------------------------------------------------- 键名常量

/**
 * L1：冻结契约指定的 canonical 键（PW-INTEGRATION-003 §3.2）。
 *
 * ⚠️ 这两个键**已在 `core/src/db/config.rs` 登记**（TECH-04 三处齐改，迁移 v11→v12）——
 * 写入应当落到 L1。下面的过渡镜像键是**历史遗留的兜底**：仅当 L1 写入失败时才回退。
 */
export const L1_KEYS = {
  provider: 'ai.provider.current',
  model: 'ai.model.current',
} as const

/**
 * 过渡镜像键：`stores/ai.ts` 也在写的两个键。
 * `landedOn === 'mirror'` 说明**没落到契约键**，上层据此设 `pendingSync`，不谎报。
 */
export const MIRROR_KEYS = {
  provider: 'ui.ai.provider',
  model: 'ui.ai.model',
} as const

/** L2 缓存键（与 `stores/ai.ts` 的 localStorage 键**完全一致**，避免两份缓存打架）。 */
export const CACHE_KEYS = {
  provider: 'ui.ai.provider',
  model: 'ui.ai.model',
  apiBase: 'ui.ai.apiBase',
} as const

/** Secret Reference 前缀（与 Python `ai/credentials.py` 的 `ref_for` 同构）。 */
export const CREDENTIAL_NAMESPACE = 'pw'

// ---------------------------------------------------------------- core 返回类型

interface CoreProviderInfo {
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

interface CoreAiInfo {
  providers: CoreProviderInfo[]
  credentialBackend: string
}

function toDescriptorInput(p: CoreProviderInfo): ProviderDescriptorInput {
  return {
    id: p.id,
    label: p.label,
    defaultEndpoint: p.defaultBase,
    defaultModel: p.defaultModel,
    needsKey: p.needsKey,
    enabled: p.enabled,
    note: p.note,
    capabilities: p.capabilities ?? [],
  }
}

// ---------------------------------------------------------------- capability（L0）

/**
 * L0 能力真相端口。
 *
 * `loadProviders()` 与 `loadSecretPresence()` 共用同一次 `ai_info` 往返
 * （`ai_info` 是 core 本地调用，但没必要为了一行布尔值再跑一趟）。
 */
export function coreCapabilityPort(): CapabilityPort {
  let memo: CoreAiInfo | null = null

  async function info(): Promise<CoreAiInfo | null> {
    if (memo) return memo
    if (!inTauri()) return null
    try {
      memo = await invokeCore<CoreAiInfo>('ai_info')
      return memo
    } catch (err) {
      logger.warn('ai-model', `读取 ai_info 失败：${String(err)}`)
      return null
    }
  }

  return {
    async loadProviders(): Promise<ProviderDescriptorInput[]> {
      const data = await info()
      return (data?.providers ?? []).map(toDescriptorInput)
    },
    async loadSecretPresence(): Promise<string[]> {
      const data = await info()
      return (data?.providers ?? [])
        .filter((p) => p.needsKey && p.hasKey === true)
        .map((p) => p.id.toLowerCase())
    },
  }
}

// ---------------------------------------------------------------- modelIo

/**
 * 模型列表 IO：经既有 `ai_list_models`（core → sidecar `/ai/models`）。
 *
 * TECH-06-A 修正一处**假绿**：原先无 core 环境 `return []`，
 * 而 `ApiAdapter` 把"不抛错"判为连通 → 会报「已连接，0 个模型」。
 * 现在如实抛错（归类为 `unreachable`），于是"拿不到"不再被显示成"已连接"。
 */
export function coreModelIo(): ModelIo {
  return {
    async listRemoteModels(providerId, opts): Promise<string[]> {
      if (!inTauri()) {
        // 没有 core 就没有探测能力 —— 抛错，让上层如实报"不可达"。
        throw new Error('unreachable：当前环境没有核心服务（需要桌面端才能探测 Provider）')
      }
      const res = await invokeCore<{ models?: string[] }>('ai_list_models', {
        provider: providerId,
        apiBase: opts.apiBase ?? '',
      })
      return Array.isArray(res?.models) ? res.models.filter((m) => !!m) : []
    },

    /**
     * Agent 健康探测（TECH-06-A）：**复用** core 既有的
     * `agents_list`（读注册清单）+ `agent_health`（真实 `GET {url}{healthCheck}`）。
     * 零新增 core 命令、零新增 config 键。
     *
     * 匹配规则：`name` 优先，否则按 `url` 归一化匹配（忽略尾斜杠与大小写）。
     * 找不到注册项 → `notFound:true`（缺前提），**不是**"探测失败"。
     */
    async agentHealth(target): Promise<{
      ok: boolean
      healthUrl?: string
      status?: number
      error?: string
      notFound?: boolean
    }> {
      if (!inTauri()) {
        return { ok: false, error: 'unreachable：当前环境没有核心服务（需要桌面端才能探测 Agent）' }
      }

      interface AgentSpecLite {
        name?: string
        url?: string
      }
      let registered: AgentSpecLite[] = []
      try {
        const raw = await invokeCore<AgentSpecLite[] | null>('agents_list')
        registered = Array.isArray(raw) ? raw : []
      } catch (err) {
        return { ok: false, error: String(err) }
      }

      const norm = (u: string | undefined): string =>
        (u ?? '').trim().replace(/\/+$/, '').toLowerCase()
      const wantName = (target.name ?? '').trim()
      const wantUrl = norm(target.url)

      const hit =
        (wantName ? registered.find((a) => (a.name ?? '').trim() === wantName) : undefined) ??
        (wantUrl ? registered.find((a) => norm(a.url) === wantUrl) : undefined)

      if (!hit || !hit.name) {
        return { ok: false, notFound: true }
      }

      try {
        const res = await invokeCore<{ healthy?: boolean; url?: string }>('agent_health', {
          name: hit.name,
        })
        return { ok: res?.healthy === true, healthUrl: res?.url }
      } catch (err) {
        // `agent_health` 失败会带 core 的原文（含 URL 与状态码）—— 原样上报，别吞
        return { ok: false, error: String(err) }
      }
    },
  }
}

// ---------------------------------------------------------------- canonical（L1）

function hasValue(v: Partial<CanonicalValues> | null): boolean {
  return !!v && (!!v.provider || !!v.model)
}

async function readPair(keys: { provider: string; model: string }): Promise<CanonicalValues> {
  const [p, m] = await Promise.all([
    invokeCore<unknown>('get_config', { key: keys.provider }),
    invokeCore<unknown>('get_config', { key: keys.model }),
  ])
  return {
    provider: typeof p === 'string' ? p : '',
    model: typeof m === 'string' ? m : '',
    apiBase: '',
  }
}

async function writePair(
  keys: { provider: string; model: string },
  values: Partial<CanonicalValues>,
): Promise<void> {
  const jobs: Array<Promise<unknown>> = []
  if (values.provider !== undefined) {
    jobs.push(invokeCore('put_config', { key: keys.provider, value: values.provider }))
  }
  if (values.model !== undefined) {
    jobs.push(invokeCore('put_config', { key: keys.model, value: values.model }))
  }
  await Promise.all(jobs)
}

/**
 * canonical 端口（L1，带过渡镜像兜底）。
 *
 * 写入顺序：**先 L1，失败落镜像**。
 * `landedOn` 如实回报 —— 上层据此设 `pendingSync`，不谎报"已落库到契约键"。
 */
export function coreCanonicalPort(): CanonicalPort {
  return {
    keys: L1_KEYS,
    mirrorKeys: MIRROR_KEYS,

    async read(): Promise<CanonicalRead | null> {
      if (!inTauri()) return null
      try {
        const l1 = await readPair(L1_KEYS)
        if (hasValue(l1)) return { values: l1, from: 'core' }
      } catch (err) {
        logger.warn('ai-model', `读 L1 canonical 失败：${String(err)}`)
      }
      try {
        const mir = await readPair(MIRROR_KEYS)
        if (hasValue(mir)) return { values: mir, from: 'mirror' }
      } catch (err) {
        logger.warn('ai-model', `读过渡镜像 canonical 失败：${String(err)}`)
      }
      return null
    },

    async write(patch): Promise<{ landedOn: CanonicalLanding }> {
      if (!inTauri()) return { landedOn: 'cache' }
      try {
        await writePair(L1_KEYS, patch)
        return { landedOn: 'core' }
      } catch {
        // L1 键未登记（core 的 KEYS 白名单会 bail）—— 不是故障，是迁移未完成
      }
      try {
        await writePair(MIRROR_KEYS, patch)
        return { landedOn: 'mirror' }
      } catch (err) {
        logger.warn('ai-model', `写过渡镜像 canonical 失败：${String(err)}`)
        return { landedOn: 'none' }
      }
    },
  }
}

// ---------------------------------------------------------------- cache（L2）

/** L2 缓存端口：localStorage。**键与 `stores/ai.ts` 一致**，两份不会打架。 */
export function localStorageCachePort(): CachePort {
  const readOne = (key: string): string => {
    try {
      return localStorage.getItem(key) ?? ''
    } catch {
      return '' // 隐私模式 / 无 DOM 环境
    }
  }
  const writeOne = (key: string, value: string): void => {
    try {
      localStorage.setItem(key, value)
    } catch {
      /* 忽略：缓存写不进去不影响功能 */
    }
  }
  return {
    read(): CanonicalValues | null {
      const provider = readOne(CACHE_KEYS.provider)
      const model = readOne(CACHE_KEYS.model)
      const apiBase = readOne(CACHE_KEYS.apiBase)
      if (!provider && !model && !apiBase) return null
      return { provider, model, apiBase }
    },
    write(values): void {
      if (values.provider !== undefined) writeOne(CACHE_KEYS.provider, values.provider)
      if (values.model !== undefined) writeOne(CACHE_KEYS.model, values.model)
      if (values.apiBase !== undefined) writeOne(CACHE_KEYS.apiBase, values.apiBase)
    },
    clear(): void {
      writeOne(CACHE_KEYS.provider, '')
      writeOne(CACHE_KEYS.model, '')
      writeOne(CACHE_KEYS.apiBase, '')
    },
  }
}

// ---------------------------------------------------------------- archive（模型清单持久化）

/**
 * 模型清单归档端口（TECH-06-B Part 1）。
 *
 * **复用既有通道**：走 canonical 同款的 `get_config` / `put_config`，键为
 * `ai.models.registry`（已在 `core/src/db/config.rs` 登记，契约 v13）——
 * **零新增 core 命令、零新增 localStorage 键**。
 *
 * 两条语义约定（`registry.ts` 据此 fail-closed）：
 * - `read()` 抛错 = 存储不可达 ⇒ Registry 拒绝覆盖写（绝不把"读不到"写成空清单）；
 * - 浏览器（无 Tauri）**直接抛错** ⇒ 归档退化为"不持久化"，
 *   **绝不**落到 localStorage —— 这是指令的红线（❌ localStorage 保存模型）。
 */
export function coreArchivePort(): ArchivePort {
  return {
    key: ARCHIVE_KEY,
    async read(): Promise<string> {
      if (!inTauri()) {
        throw new Error('archive：当前环境没有核心服务（模型清单只在桌面端持久化）')
      }
      const raw = await invokeCore<unknown>('get_config', { key: ARCHIVE_KEY })
      return typeof raw === 'string' ? raw : ''
    },
    async write(raw: string): Promise<void> {
      if (!inTauri()) {
        throw new Error('archive：当前环境没有核心服务（模型清单只在桌面端持久化）')
      }
      await invokeCore('put_config', { key: ARCHIVE_KEY, value: raw })
    },
  }
}

// ---------------------------------------------------------------- secret

/**
 * 凭据端口（TASK-06 的 Secret Storage 一段）。
 *
 * 三条铁律（与红线 V1 一致）：
 * 1. 明文只在这一条链上流动：`setCredential()` 入参 → `ai_set_credential` → 系统凭据库；
 * 2. 返回值**只有掩码**（`sk-****abcd`）；
 * 3. 除 `refFor()` 的字符串拼接外，本端口**不持有任何密钥**。
 */
export function coreSecretPort(): SecretPort {
  return {
    refFor(providerId: string): string {
      return `${CREDENTIAL_NAMESPACE}/${providerId.trim().toLowerCase()}/default`
    },
    async has(providerId: string): Promise<boolean> {
      if (!inTauri()) return false
      try {
        const data = await invokeCore<CoreAiInfo>('ai_info')
        const hit = (data?.providers ?? []).find(
          (p) => p.id.toLowerCase() === providerId.trim().toLowerCase(),
        )
        return hit ? hit.hasKey !== false : false
      } catch {
        return false
      }
    },
    async set(providerId: string, secret: string) {
      const pid = providerId.trim().toLowerCase()
      const ref = `${CREDENTIAL_NAMESPACE}/${pid}/default`
      if (!inTauri()) {
        // 浏览器环境没有凭据库 —— 明确失败，不假装成功
        throw new Error('当前环境不支持凭据存储（需要桌面端）')
      }
      const res = await invokeCore<{ keyMask?: string; backend?: string }>('ai_set_credential', {
        provider: pid,
        secret,
      })
      return {
        provider: pid,
        ref,
        mask: res?.keyMask ?? '',
        backend: res?.backend ?? '',
      }
    },
    async remove(providerId: string): Promise<boolean> {
      if (!inTauri()) return false
      try {
        const res = await invokeCore<{ removed?: boolean } | boolean>('ai_delete_credential', {
          provider: providerId.trim().toLowerCase(),
        })
        return typeof res === 'boolean' ? res : res?.removed !== false
      } catch {
        return false
      }
    },
  }
}

// ---------------------------------------------------------------- 组合根

export interface CreateModelRegistryOptions {
  /** 覆盖任意端口（测试用）。 */
  ports?: Partial<RegistryPorts>
}

/**
 * 生产组合根：把各端口的 core 实现拼成一个 `ModelRegistry`。
 *
 * ```ts
 * const reg = createCoreModelRegistry()
 * await reg.hydrate()                 // 读 L0 + L1
 * reg.models.list()                   // 见 createModelsApi()
 * ```
 *
 * **本轮不注入 `window`、不被任何页面 import** —— 零接线，故零影响。
 */
export function createCoreModelRegistry(opts: CreateModelRegistryOptions = {}): ModelRegistry {
  const ports: RegistryPorts = {
    io: coreModelIo(),
    capability: coreCapabilityPort(),
    canonical: coreCanonicalPort(),
    cache: localStorageCachePort(),
    secret: coreSecretPort(),
    // TECH-06-B：模型清单唯一持久化来源（键 ai.models.registry）。
    // 漏掉这一行 = 模型管理退化为内存态 —— verify_tech06b 的接线断言专门盯它。
    archive: coreArchivePort(),
    ...opts.ports,
  }
  return new ModelRegistry(ports)
}

/** 内存端口（纯浏览器/单测环境用；默认不持久化）。 */
export function memoryPorts(seed?: {
  providers?: ProviderDescriptorInput[]
  remoteModels?: Record<string, string[]>
  /** TECH-06-A：Agent 探测的桩（不传则模拟"未实现该端口"）。 */
  agentProbe?: (target: { name?: string; url?: string }) =>
    | { ok: boolean; healthUrl?: string; status?: number; error?: string; notFound?: boolean }
    | Promise<{ ok: boolean; healthUrl?: string; status?: number; error?: string; notFound?: boolean }>
  /**
   * TECH-06-B：归档存根（传入才注入 archive 端口 —— 缺省保持"内存态"旧语义不变）。
   * `raw` 就是串；测试据此断言"落盘的内容"与"重启后恢复的内容"。
   */
  archiveBox?: { raw: string }
}): RegistryPorts {
  const providers = seed?.providers ?? []
  const remote = seed?.remoteModels ?? {}
  const kv = new Map<string, string>()
  const creds = new Set<string>()
  return {
    io: {
      async listRemoteModels(providerId): Promise<string[]> {
        // 测试桩：未登记即视为"连通但没模型"（保持既有语义，不顺手收紧）
        return remote[providerId] ?? []
      },
      // 桩可以同步返回，但端口契约是 async —— 这里包一层，避免调用方要区分两种
      ...(seed?.agentProbe
        ? { agentHealth: async (t: { name?: string; url?: string }) => seed.agentProbe!(t) }
        : {}),
    },
    capability: {
      async loadProviders() {
        return providers
      },
      async loadSecretPresence() {
        return [...creds]
      },
    },
    canonical: {
      keys: L1_KEYS,
      mirrorKeys: MIRROR_KEYS,
      async read(): Promise<CanonicalRead | null> {
        const provider = kv.get(L1_KEYS.provider) ?? ''
        const model = kv.get(L1_KEYS.model) ?? ''
        if (!provider && !model) return null
        return { values: { provider, model, apiBase: '' }, from: 'core' }
      },
      async write(patch) {
        if (patch.provider !== undefined) kv.set(L1_KEYS.provider, patch.provider)
        if (patch.model !== undefined) kv.set(L1_KEYS.model, patch.model)
        return { landedOn: 'core' }
      },
    },
    cache: {
      read: () => null,
      write: () => undefined,
      clear: () => undefined,
    },
    secret: {
      refFor: (id) => `${CREDENTIAL_NAMESPACE}/${id}/default`,
      async has(id) {
        return creds.has(id)
      },
      async set(id, secret) {
        creds.add(id)
        return { provider: id, ref: `${CREDENTIAL_NAMESPACE}/${id}/default`, mask: maskOf(secret), backend: 'memory' }
      },
      async remove(id) {
        return creds.delete(id)
      },
    },
    // 归档存根：只有显式给了 archiveBox 才注入 —— 内存端口的缺省语义保持"不持久化"
    ...(seed?.archiveBox
      ? {
          archive: {
            key: ARCHIVE_KEY,
            read: async () => seed.archiveBox!.raw,
            write: async (raw: string) => {
              seed.archiveBox!.raw = raw
            },
          } satisfies ArchivePort,
        }
      : {}),
  }
}

/** 便利再导出（UI 侧只 import 本文件即可）。 */
export { maskOf }
export type { ModelDescriptor, ModelProfile }
