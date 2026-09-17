/**
 * AI Model Domain —— 只读消费者接口（TECH-03-B · TASK-04）
 *
 * ## 它解决什么
 * TECH-03-A 把 `ModelRegistry` 立成了"模型管理的唯一读写口"，但刻意**零接线**：
 * 没有任何页面 import 它，于是 canonical（用户到底在用哪个模型）没有第二双眼睛看得到。
 *
 * 本文件补上**只读的那一半**：把 Registry 投影成 UI 能直接渲染的读模型，
 * 且**在类型层面就不提供任何写方法** —— 消费者拿到的对象上根本没有
 * `setCanonical` / `add` / `update` / `remove` / `setDefault` / `check` / `setCredential`。
 * 想改模型只能走 `ModelRegistry` 本体（UI 侧目前只有设置页），本层改不了。
 *
 * ```
 *   ModelRegistry（可读写）
 *        │  只投影读方法
 *        ▼
 *   createModelReadOnly()  ──>  { current(), list(), providers(), subscribe() }   ← 冻结
 *        │
 *        ▼
 *   components/AiSidebar.vue  "当前模型：xxx"（纯展示）
 * ```
 *
 * ## 与 `stores/ai.ts` 的关系（为什么不是替换）
 * `stores/ai.ts` 管的是"这次对话发给谁"（请求级参数 + 宽度/折叠等 UI 状态）；
 * 本层管的是"系统当前认定的默认模型是什么"（canonical）。
 * 两者**并行存在**，本轮不做互相覆盖 —— 接线只是让 UI 能"看见" canonical，
 * 端到端的替换（用 canonical 驱动发送参数）属于后续阶段。
 *
 * ## 零框架依赖
 * 同领域层：不 import Vue、不 import `@/`。IO 全在被包裹的 Registry 里，
 * 所以本文件可以被 Node 直接编译执行（verify_tech03b.py T4）。
 */

import type {
  CanonicalSource,
  CanonicalValues,
  ModelListEntry,
  ModelRegistry,
} from './registry'
import type { ProviderDescriptor } from './provider'

// ---------------------------------------------------------------- 读模型

/** 顶栏"当前模型"要显示的全部信息。**全部是推导出来的，不含任何写口。** */
export interface CurrentModelView {
  /** canonical 是否已设置（`false` = 用户从没选过，或读不到）。 */
  set: boolean
  /** 主标题：模型名（`name` 优先，回退 `model`）。未设置时为 `未配置`。 */
  label: string
  /** 副标题：Provider 标签（+ 异常说明）。 */
  detail: string
  /** 角标：`离线` / `待同步` / `已失效`；无异常时为空串。 */
  badge: string
  /** hook 上的一句人话，说清这个值是从哪读到的。 */
  title: string
  /** 归约后的来源（core / mirror / cache / none）。 */
  source: CanonicalSource
  /** 读到的真身不在 L1（core 不可达 / 键未登记）。 */
  stale: boolean
  /** 最近一次写入没落到 L1。 */
  pendingSync: boolean
  /** canonical 有值但注册表里找不到对应模型。 */
  dangling: boolean
  /** 内联的诊断（供验收脚本断言；UI 不显示）。 */
  canonical: CanonicalValues
}

/** 只读消费者门面。**没有任何写方法 —— 这是本接口的全部意义。** */
export interface ModelReadOnly {
  /** 当前默认模型（canonical 投影）。同步、纯读。 */
  current(): CurrentModelView
  /** 全部模型列表（含状态/默认标记/是否配了凭据）。 */
  list(opts?: { onlyEnabled?: boolean }): ModelListEntry[]
  /** 系统当前有哪些 Provider（L0 只读投影）。 */
  providers(): ProviderDescriptor[]
  /** 某个 Provider 是否已配凭据（**只回布尔，不问值**）。 */
  hasCredential(providerId: string): boolean
  /** 订阅变更（Registry 每次 mutate / hydrate / refresh 都会通知）。返回退订函数。 */
  subscribe(fn: (reason: string, revision: number) => void): () => void
}

// ---------------------------------------------------------------- 纯函数（可单独测）

const SOURCE_LABEL: Record<CanonicalSource, string> = {
  core: '契约键（core config）',
  mirror: '过渡镜像键（core config，待迁移到契约键）',
  cache: '本地缓存（core 不可达时的兜底）',
  none: '未设置',
}

function labelOfSource(s: CanonicalSource): string {
  return SOURCE_LABEL[s] ?? '未知来源'
}

function providerLabel(registry: ModelRegistry, id: string): string {
  const d = registry.providers.getProvider(id)
  return d?.label || id || '（未知 Provider）'
}

/**
 * 把 `registry.getDefault()` 归约成顶栏读模型。**纯函数**：同样的 Registry 状态得同样结果。
 */
export function resolveCurrentModel(registry: ModelRegistry): CurrentModelView {
  const d = registry.getDefault()
  const c = d.canonical

  if (d.unset) {
    return {
      set: false,
      label: '未配置',
      detail: '尚未选择模型',
      badge: '',
      title: `当前模型来自 ModelRegistry canonical（${labelOfSource(c.source)}）：尚未设置`,
      source: c.source,
      stale: c.stale,
      pendingSync: c.pendingSync,
      dangling: false,
      canonical: { provider: c.provider, model: c.model, apiBase: c.apiBase },
    }
  }

  if (d.dangling) {
    // canonical 指向的模型不在注册表里（典型：模型被删了）—— 如实显示，不假装有模型
    return {
      set: true,
      label: c.model || c.provider,
      detail: providerLabel(registry, c.provider),
      badge: '已失效',
      title: `当前模型来自 ModelRegistry canonical（${labelOfSource(c.source)}）：注册表中已无此模型`,
      source: c.source,
      stale: c.stale,
      pendingSync: c.pendingSync,
      dangling: true,
      canonical: { provider: c.provider, model: c.model, apiBase: c.apiBase },
    }
  }

  const p = d.profile!
  const badge = c.pendingSync ? '待同步' : c.stale ? '离线' : ''
  return {
    set: true,
    label: p.name || p.model,
    detail: providerLabel(registry, p.provider),
    badge,
    title:
      `当前模型来自 ModelRegistry canonical（${labelOfSource(c.source)}）` +
      (badge ? ` · ${badge}` : ''),
    source: c.source,
    stale: c.stale,
    pendingSync: c.pendingSync,
    dangling: false,
    canonical: { provider: c.provider, model: c.model, apiBase: c.apiBase },
  }
}

// ---------------------------------------------------------------- 门面

/**
 * 从 Registry 取出**只读**消费者。
 *
 * 返回对象被 `Object.freeze`：调用方既没有写方法可调，也无法往里塞一个。
 */
export function createModelReadOnly(registry: ModelRegistry): ModelReadOnly {
  const api: ModelReadOnly = {
    current: () => resolveCurrentModel(registry),
    list: (opts) => registry.list(opts),
    providers: () => registry.listProviders(),
    hasCredential: (providerId) => registry.hasCredential(providerId),
    subscribe: (fn) =>
      registry.subscribe((m) => {
        fn(m.reason, m.revision)
      }),
  }
  return Object.freeze(api)
}

/** 所有"写方法"的名字 —— 验收脚本用它断言只读面确实一个都没漏出来。 */
export const MUTATOR_NAMES = [
  'add',
  'update',
  'remove',
  'setDefault',
  'setCanonical',
  'refreshCanonical',
  'check',
  'setCredential',
  'removeCredential',
  'clear',
  'hydrate',
  'importProfiles',
  'exportProfiles',
] as const
