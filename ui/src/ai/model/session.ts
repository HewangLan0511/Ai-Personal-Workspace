/**
 * AI Model Domain —— 模型会话（TECH-04 §一）· **纯逻辑层，零 `@/` 依赖**
 *
 * ## 为什么和 `bridge.ts` 分开
 * 与 `registry.ts`（领域）↔ `ports.ts`（IO 适配）的分法一致：
 * **决策与编排留在本文件**（可在 Node 里被直接编译执行 ⇒ 迁移路径可被机器验证），
 * `bridge.ts` 只负责"造一个真实 Registry 并把它接成单例"。
 *
 * ```
 *   bridge.ts（薄接线：createCoreModelRegistry → 单例）
 *        │  注入 registry
 *        ▼
 *   session.ts（本文件：启动解析 / 写落点 / 一次性迁移 / 订阅）
 *        │  纯决策
 *        ▼
 *   selection.ts（resolveSelection / needsMigration —— 无 IO 的纯函数）
 * ```
 *
 * ## 它保证的那件事
 * 会话里的"当前模型"**只从 canonical 来、只往 canonical 写**，
 * 于是「界面显示的值」与「请求实际发出的值」由构造保证一致
 * —— 这正是 TECH-04 §一 要消除的「显示模型 ≠ 实际调用模型」。
 */

import type { CanonicalSnapshot, ModelRegistry } from './registry'
import {
  isSet,
  needsMigration,
  resolveSelection,
  type CanonicalLike,
  type ResolutionSource,
  type Selection,
} from './selection'

export interface BootResolution {
  /** 本次应采用的选择（= 请求依据）。 */
  selection: Selection
  /** 目标的来源。 */
  source: ResolutionSource
  /** 是否把界面选择前向写入了 canonical（迁移步）。 */
  wroteCanonical: boolean
  /** 是否需要让界面跟随 canonical。 */
  adopted: boolean
  /** 迁移结果。 */
  migrated: 'none' | 'mirrored-to-core' | 'failed'
  reason: string
}

export interface MigrationResult {
  migrated: boolean
  from: string
  to: string
}

export interface ModelSession {
  readonly registry: ModelRegistry
  /** 保证已 hydrate（幂等）。 */
  ready(): Promise<void>
  /** 当前 canonical（`null` = 从未设置过）。纯读。 */
  current(): CanonicalLike | null
  /** 启动期解析：决定这次会话用哪个 provider/model。 */
  resolveAtBoot(selection: Partial<Selection>): Promise<BootResolution>
  /** 界面选择变化 → 写 canonical。 */
  syncSelection(selection: Partial<Selection>): Promise<CanonicalSnapshot | null>
  /** 一次性前向迁移：镜像/缓存里的老值 → 正式落点 L1（不删旧值）。 */
  migrateIfNeeded(): Promise<MigrationResult>
  /** 订阅 canonical（先发一次当前值）。 */
  subscribe(fn: (c: CanonicalLike | null) => void): () => void
}

const EMPTY: Selection = { provider: '', model: '', apiBase: '' }

/**
 * 造一个模型会话。**registry 由外部注入** ⇒ 本函数不含任何 IO 构造逻辑，
 * 因此可以被 Node 直接驱动（verify_tech04.py T1）。
 */
export function createModelSession(registry: ModelRegistry): ModelSession {
  let hydrating: Promise<void> | null = null
  let migrationAttempted = false

  async function ready(): Promise<void> {
    if (registry.isHydrated()) return
    if (!hydrating) {
      hydrating = registry
        .hydrate()
        .then(() => undefined)
        .catch(() => undefined)
    }
    await hydrating
  }

  function like(): CanonicalLike {
    const c = registry.getCanonical()
    return {
      provider: c.provider,
      model: c.model,
      apiBase: c.apiBase,
      source: c.source,
      stale: c.stale,
      pendingSync: c.pendingSync,
    }
  }

  function current(): CanonicalLike | null {
    const c = like()
    return isSet(c) ? c : null
  }

  /** 把"provider+model"补进 Registry —— 否则顶栏会把正常配置误报成「已失效」（dangling）。 */
  function ensureProfile(provider: string, model: string): void {
    if (!provider || !model) return
    const hit = registry.list().some((e) => e.provider === provider && e.model === model)
    if (hit) return
    try {
      registry.add({ provider, model })
    } catch {
      /* 并发/重复/未开放：显示正确性失败不该抛给调用方 */
    }
  }

  async function writeCanonical(sel: Selection): Promise<CanonicalSnapshot | null> {
    try {
      return await registry.setCanonical({
        provider: sel.provider,
        model: sel.model,
        apiBase: sel.apiBase,
      })
    } catch {
      return null
    }
  }

  async function migrateToCore(): Promise<boolean> {
    const c = like()
    if (!isSet(c)) return false
    const next = await writeCanonical({ provider: c.provider, model: c.model, apiBase: c.apiBase })
    return next !== null && next.source === 'core'
  }

  async function resolveAtBoot(selection: Partial<Selection>): Promise<BootResolution> {
    await ready()
    const canonical = like()
    const r = resolveSelection(canonical, selection)

    if (r.source === 'none') {
      return {
        selection: EMPTY,
        source: 'none',
        wroteCanonical: false,
        adopted: false,
        migrated: 'none',
        reason: r.reason,
      }
    }

    // 目标若指向未登记/未开放的 Provider，`setCanonical` 会拒绝（契约要求）——
    // 这时**不静默兜底**，如实报 `failed`。
    let wrote = false
    let migrated: BootResolution['migrated'] = 'none'

    if (r.writeCanonical) {
      wrote = (await writeCanonical(r.target)) !== null
      if (wrote && needsMigration(canonical)) migrated = 'mirrored-to-core'
    } else if (needsMigration(canonical)) {
      // canonical 有值且界面没改它 → 顺手把老数据搬到正式落点（一次性）
      const ok = await migrateToCore()
      migrated = ok ? 'mirrored-to-core' : 'failed'
    }

    ensureProfile(r.target.provider, r.target.model)

    return {
      selection: r.target,
      source: r.source,
      wroteCanonical: wrote,
      adopted: r.adoptIntoSelection,
      migrated,
      reason: r.reason,
    }
  }

  async function syncSelection(selection: Partial<Selection>): Promise<CanonicalSnapshot | null> {
    await ready()
    const provider = String(selection.provider ?? '').trim().toLowerCase()
    const model = String(selection.model ?? '').trim()
    const apiBase = String(selection.apiBase ?? '').trim()

    if (!provider) return null
    const d = registry.providers.getProvider(provider)
    if (!d || !d.enabled) return null // 契约：canonical 不得指向未注册/未开放 Provider

    ensureProfile(provider, model || d.defaultModel)
    return writeCanonical({
      provider,
      model: model || d.defaultModel,
      apiBase: apiBase || d.defaultEndpoint || '',
    })
  }

  async function migrateIfNeeded(): Promise<MigrationResult> {
    await ready()
    const c = like()
    if (!needsMigration(c) || migrationAttempted) {
      return { migrated: false, from: c.source, to: c.source }
    }
    migrationAttempted = true
    const ok = await migrateToCore()
    return { migrated: ok, from: c.source, to: registry.getCanonical().source }
  }

  function subscribe(fn: (c: CanonicalLike | null) => void): () => void {
    void ready().then(() => {
      fn(current())
    })
    return registry.subscribe(() => {
      fn(current())
    })
  }

  return { registry, ready, current, resolveAtBoot, syncSelection, migrateIfNeeded, subscribe }
}
