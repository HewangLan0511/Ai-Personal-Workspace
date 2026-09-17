/**
 * AI Model Domain —— 选择解析（TECH-04 §一）· **纯决策层，零 IO**
 *
 * ## 它解决的那个 bug
 * TECH-03-B 交付后，AI 侧栏顶部显示的「当前模型」读的是 **canonical**（ModelRegistry），
 * 而 `stores/ai.ts` 发请求时用的是**它自己那份** `providerId` / `model`（来自 localStorage）。
 * 两个独立来源 ⇒ 一旦不同步，用户看到 A、实际发给 B，而且**没有任何机制保证它们一致**。
 *
 * 本文件把"谁说了算"变成一个**纯函数决策**，这样它可以被机器枚举验证：
 *
 * ```
 *   canonical（冻结落点，持久化真相）  ┐
 *                                     ├─► resolveSelection() ─► 本次应采用的目标 + 要不要回写
 *   界面选择（会话内，localStorage）    ┘
 * ```
 *
 * ## 三条规则（canonical 优先）
 * 1. canonical 有值 ⇒ **以 canonical 为准**；界面选择若与它不同，收敛到 canonical
 *    （`adoptIntoSelection=true`）。理由：canonical 是 PW-INTEGRATION-003 冻结的落点，
 *    也是"请求依据"的唯一定义处；界面选择要生效必须**先写进 canonical**（见规则 2）。
 * 2. canonical 为空而界面选择有值 ⇒ 采用界面选择，并**前向写入 canonical**
 *    （`writeCanonical=true`）—— 这是"从旧行为平滑迁移"的那一步，写的是冻结键而不是新键。
 * 3. 两者都空 ⇒ 什么都不做（`source='none'`），UI 显示"未配置"。
 *
 * ## 为什么规则 1 不是"覆盖用户选择"
 * `setProvider()` / `setModel()` 会**同步写 canonical**，所以用户主动改选择时两者本就一致；
 * 出现不一致只可能是"会话外被改过"（旧数据 / 别处写过镜像），此时收敛到落点才是对的。
 *
 * ## 零依赖
 * 不 import Vue / `@/`。纯函数 ⇒ 可以在 Node 里枚举全部输入组合（verify_tech04.py T1）。
 */

/** 一次"用哪个 provider + 哪个模型"的选择。 */
export interface Selection {
  provider: string
  model: string
  apiBase: string
}

export interface CanonicalLike {
  provider: string
  model: string
  apiBase: string
  source: 'core' | 'mirror' | 'cache' | 'none'
  stale: boolean
  pendingSync: boolean
}

export type ResolutionSource = 'canonical' | 'selection' | 'none'

export interface SelectionResolution {
  /** 本次请求/显示应当采用的目标。 */
  target: Selection
  /** 这个目标是从哪来的。 */
  source: ResolutionSource
  /** 需要把 `target` 前向写入 canonical（落点为空、或落点与目标不同）。 */
  writeCanonical: boolean
  /** 需要把 canonical 采纳为会话选择（落点有值，界面侧应跟随）。 */
  adoptIntoSelection: boolean
  /** 人话原因（进日志/验收输出，不用于判断）。 */
  reason: string
}

function norm(s: string | null | undefined): string {
  return String(s ?? '').trim()
}

/** 一份选择是否"有内容"。 */
export function isSet(sel: Partial<Selection>): boolean {
  return !!norm(sel.provider) || !!norm(sel.model)
}

/** 两份选择是否等价（按规范化后的值比较；apiBase 不参与 —— 它可随模型变化而省略）。 */
export function sameSelection(a: Partial<Selection>, b: Partial<Selection>): boolean {
  return norm(a.provider).toLowerCase() === norm(b.provider).toLowerCase()
    && norm(a.model) === norm(b.model)
}

function normalize(sel: Partial<Selection>): Selection {
  return { provider: norm(sel.provider).toLowerCase(), model: norm(sel.model), apiBase: norm(sel.apiBase) }
}

/**
 * 决策：本次应采用哪个 provider/model，以及要不要写回。
 *
 * **纯函数**：同样的入参永远同样的出参；不读任何全局状态。
 */
export function resolveSelection(
  canonical: Partial<CanonicalLike>,
  selection: Partial<Selection>,
): SelectionResolution {
  const c = normalize(canonical)
  const s = normalize(selection)
  const cSet = isSet(c)
  const sSet = isSet(s)

  if (!cSet && !sSet) {
    return {
      target: { provider: '', model: '', apiBase: '' },
      source: 'none',
      writeCanonical: false,
      adoptIntoSelection: false,
      reason: 'canonical 与界面选择均为空 → 未配置',
    }
  }

  if (!cSet && sSet) {
    return {
      // 采用界面选择，并把 apiBase 一起带过去（canonical 没有 apiBase 的持久键）
      target: { provider: s.provider, model: s.model, apiBase: s.apiBase },
      source: 'selection',
      writeCanonical: true,
      adoptIntoSelection: false,
      reason: 'canonical 未设置、界面有选择 → 采用界面选择并前向写入 canonical（迁移步）',
    }
  }

  if (cSet && !sSet) {
    return {
      target: { provider: c.provider, model: c.model, apiBase: c.apiBase },
      source: 'canonical',
      writeCanonical: false,
      adoptIntoSelection: true,
      reason: '界面未选、canonical 有值 → 以 canonical 为准（并由界面跟随）',
    }
  }

  // 两者都有值
  if (sameSelection(c, s)) {
    return {
      target: { provider: c.provider, model: c.model, apiBase: s.apiBase || c.apiBase },
      source: 'canonical',
      writeCanonical: false,
      adoptIntoSelection: false,
      reason: 'canonical 与界面选择一致 → 无操作',
    }
  }
  return {
    target: { provider: c.provider, model: c.model, apiBase: c.apiBase },
    source: 'canonical',
    writeCanonical: false,
    adoptIntoSelection: true,
    reason: 'canonical 与界面选择不一致 → 收敛到 canonical（落点是唯一事实来源）',
  }
}

/**
 * 是否需要对 canonical 做**一次性前向迁移**。
 *
 * 判据：canonical 有值，但它的真身不在 L1（`source !== 'core'`）—— 典型是
 * TECH-03-A/B 期间只写过过渡镜像键的老数据。TECH-04 登记 L1 键后，把它搬过去即可。
 * **不删旧值**：老版本回滚仍然能跑。
 */
export function needsMigration(canonical: Partial<CanonicalLike>): boolean {
  if (!isSet(canonical)) return false
  return canonical.source !== 'core'
}
