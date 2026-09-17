/**
 * AI 助手应用层 —— 组合根（TECH-05-D §P1-A）
 *
 * ## 它只做三件事
 * ① 造一个**共享**的 `ModelRegistry`（与顶栏 / 模型管理页同一个实例，来自 `ai/model/bridge`）；
 * ② 把 core 的传输端口与各层候选值读取器拼成 `AssistantService`；
 * ③ 暴露语义化入口（`getSharedAssistant()`）。
 *
 * **不含任何业务判断** —— 判断在 `request.ts` / `service.ts`。
 *
 * ## 与 `ai/model/bridge.ts` 的关系（对称，不重叠）
 * | 桥 | 单例是什么 | 谁在用 |
 * |----|-----------|--------|
 * | `ai/model/bridge.ts` | `ModelSession`（Registry + canonical 会话） | 顶栏 / 模型管理页 / 设置页 |
 * | `ai/assistant/bridge.ts`（本文件） | `AssistantService`（解析 + 边界 + 传输） | AI 助手页 / AI 侧栏 |
 * 两者共用**同一个** Registry 实例 —— 这就是"页面看到的模型 == 请求用的模型"那件事的实现方式。
 *
 * ## 它读哪些层（对齐冻结契约）
 * ```
 *   canonical        ← registry.getDefault()（共享实例，唯一事实来源）
 *   suggestion       ← config `ai.active_profile`（模式 ai_profile 的运行时投影）
 *   headlessDefault  ← config `ai.default_provider`
 *   firstEnabled     ← registry.listProviders()（L0 兜底）
 * ```
 * `suggestion` / `headlessDefault` 读 config，属 IO，所以放在本文件（组合根）；
 * `service.ts` 保持零 IO、可被 Node 直接执行。
 *
 * ## 为什么不是"直接 new 一个 Registry"
 * TECH-03-B 的教训（见 `ai/model/bridge.ts` 头部）：自建 Registry 会让
 * 「显示的 canonical」与「请求用的选择」变成两个互不知道的对象。
 * 本文件因此**只取共享实例**，没有第二条路。
 */

import { configApi } from '@/api/configService'
import { getSharedRegistry } from '@/ai/model/bridge'
import type { ModelRegistry } from '@/ai/model/registry'
import { logger } from '@/utils/logger'

import { createAssistantService, type AssistantService } from './service'
import { coreAiTransport } from './transport'
import type { TargetCandidate } from './request'

/** 契约里 L3 建议层的运行时投影键（`docs/contracts/.../ai-provider-current.v1.valid.json`）。 */
export const SUGGESTION_KEY = 'ai.active_profile'
/** 契约里 L4 无 UI 调用者回退键。 */
export const HEADLESS_DEFAULT_KEY = 'ai.default_provider'

/**
 * 把"只给了 provider"的候选补成完整目标。
 *
 * 为什么需要：`AiProfile` 结构里**只有 provider**（`core/src/scheduler/repository.rs`），
 * `ai.default_provider` 也只是个 provider 名 —— 而请求需要 model。
 * 补的规则是"取注册表里该 Provider 的默认模型"，即用 L0 的已知信息补 L3/L4 的缺口，
 * 而不是凭空猜一个模型名。
 */
function completeWithProviderDefault(registry: ModelRegistry, provider: string): TargetCandidate | null {
  const pid = provider.trim().toLowerCase()
  if (!pid) return null
  const p = registry.listProviders().find((x) => x.id.toLowerCase() === pid)
  return {
    provider: pid,
    model: p?.defaultModel ?? '',
    apiBase: p?.defaultEndpoint ?? '',
  }
}

/** 读 L3 建议层（模式 `ai_profile` 的投影）。读不到 / 空 → `null`（该层不可用）。 */
async function readSuggestion(registry: ModelRegistry): Promise<Partial<TargetCandidate> | null> {
  try {
    const raw = await configApi.get<Record<string, unknown> | null>(SUGGESTION_KEY, null)
    const provider = String((raw as Record<string, unknown> | null)?.provider ?? '').trim()
    if (!provider) return null
    return completeWithProviderDefault(registry, provider)
  } catch (e) {
    // 读不到建议层不是错误 —— 解析顺序继续往下走
    logger.warn('ai-assistant', `读取建议层失败（跳过）：${String(e)}`)
    return null
  }
}

/** 读 L4 无 UI 调用者回退。 */
async function readHeadlessDefault(registry: ModelRegistry): Promise<Partial<TargetCandidate> | null> {
  try {
    const provider = String(await configApi.get<string>(HEADLESS_DEFAULT_KEY, '')).trim()
    if (!provider) return null
    return completeWithProviderDefault(registry, provider)
  } catch (e) {
    logger.warn('ai-assistant', `读取 headlessDefault 失败（跳过）：${String(e)}`)
    return null
  }
}

let service: AssistantService | null = null

/**
 * 全应用唯一的 AI 助手应用服务。
 *
 * 惰性创建（构造不碰 IO）。`registry` 取**共享实例** —— 与顶栏、
 * 模型管理页、AI 侧栏是同一个对象，这一点由验收脚本用 `===` 直接证明。
 */
export function getSharedAssistant(): AssistantService {
  if (service) return service
  const registry = getSharedRegistry()
  service = createAssistantService({
    registry,
    transport: coreAiTransport(),
    sources: {
      suggestion: () => readSuggestion(registry),
      headlessDefault: () => readHeadlessDefault(registry),
    },
  })
  return service
}

/** 验收/测试用：重置单例。 */
export function __resetAssistantForTest(): void {
  service = null
}

/** 验收/测试用：注入自定义服务（脚本用假传输驱动真实编排逻辑）。 */
export function __setAssistantForTest(s: AssistantService | null): void {
  service = s
}

export type { AssistantService }
