/**
 * AI Model Domain —— canonical 桥（TECH-04 §一）· **薄接线层**
 *
 * ## 它在数据链里的位置
 * ```
 *   模型管理界面（AI 侧栏 Provider/模型选择 · 设置页密钥）
 *        │  ① setProvider() / setModel() → bridge.syncSelection() → canonical（L1）
 *        ▼
 *   Model Registry（唯一读写口） ←── bridge.getSharedRegistry()（全应用同一个实例）
 *        │  ② 启动时 bridge.resolveAtBoot() → 采纳 canonical 作为会话选择
 *        ▼
 *   Canonical Provider（ai.provider.current / ai.model.current）
 *        │  ③ stores/ai.ts 的 send() 用会话选择（== canonical）发请求
 *        ▼
 *   AI 助手
 * ```
 *
 * ## 为什么"单实例"是硬要求
 * TECH-03-B 的 `useCurrentModel.ts` 自己 new 了一个 Registry —— 于是**顶栏显示的 canonical**
 * 与 **AI store 的选择** 是两个互不知道的对象，这正是「显示模型 ≠ 实际调用模型」的温床。
 * 本文件把它收敛成模块级单例：显示与调用共用同一份真相，**结构上不可能不一致**。
 *
 * ## 本文件只做三件事
 * ① 造一个真实的 Registry（`createCoreModelRegistry()`，即 ports.ts 的组合根）；
 * ② 把它包成单例会话（`createModelSession()`，逻辑全在 `session.ts`）；
 * ③ 把会话的语义化入口转出来。**不含任何业务判断** —— 判断在 `selection.ts` / `session.ts`。
 *
 * ## 谁写 canonical
 * 只有本层（代表用户在界面上的选择）与将来的模型管理页会写；`useCurrentModel.ts`
 * 保持**只读**（只投影供显示）。这样"谁改 canonical"永远只有一处可查。
 */

import { createCoreModelRegistry } from './ports'
import type { ModelRegistry } from './registry'
import type { CanonicalLike, Selection } from './selection'
import { createModelSession, type BootResolution, type MigrationResult, type ModelSession } from './session'
import type { CanonicalSnapshot } from './registry'

export type { BootResolution, MigrationResult, ModelSession } from './session'
export type { CanonicalLike, Selection } from './selection'

let session: ModelSession | null = null

function ensureSession(): ModelSession {
  if (!session) session = createModelSession(createCoreModelRegistry())
  return session
}

/**
 * 全应用唯一的 ModelRegistry。**顶栏显示与 AI 请求依据共用它。**
 * 惰性创建（构造不碰 IO）。
 */
export function getSharedRegistry(): ModelRegistry {
  return ensureSession().registry
}

/** 保证已 hydrate（幂等；并发调用共享同一次装载）。 */
export function ensureHydrated(): Promise<void> {
  return ensureSession().ready()
}

/** 当前 canonical（`null` = 从未设置过）。纯读。 */
export function currentCanonical(): CanonicalLike | null {
  return ensureSession().current()
}

/** 启动期解析：决定这次会话用哪个 provider/model（`stores/ai.ts::init` 调它）。 */
export function resolveAtBoot(selection: Partial<Selection>): Promise<BootResolution> {
  return ensureSession().resolveAtBoot(selection)
}

/** 界面选择变化 → 写 canonical（`setProvider` / `setModel` 调它）。 */
export function syncSelection(selection: Partial<Selection>): Promise<CanonicalSnapshot | null> {
  return ensureSession().syncSelection(selection)
}

/** 一次性前向迁移：镜像/缓存里的老值 → 正式落点 L1（**不删旧值**）。 */
export function migrateIfNeeded(): Promise<MigrationResult> {
  return ensureSession().migrateIfNeeded()
}

/** 订阅 canonical 变化（先发一次当前值）。 */
export function subscribeCanonical(fn: (c: CanonicalLike | null) => void): () => void {
  return ensureSession().subscribe(fn)
}

/** 验收/测试用：重置单例。 */
export function __resetBridgeForTest(): void {
  session = null
}

/** 验收/测试用：注入一个自定义会话（verify 脚本用假 Registry 驱动真实逻辑）。 */
export function __setSessionForTest(s: ModelSession | null): void {
  session = s
}
