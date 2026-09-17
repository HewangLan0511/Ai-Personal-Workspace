/**
 * 模型「显示状态」词表（TECH-06-A）
 *
 * ## 为什么单独一个纯函数文件
 *
 * 归约链本来就是两段，之前只有第一段：
 * ```
 *   ModelProfile.status   ──entryStatusOf()──>  ModelEntryStatus   （领域内部态，registry.ts:196）
 *                            ready / unchecked / unavailable / disabled
 *                                       │
 *                                       └──displayStatusOf()──>  DisplayStatus   ← 本文件
 *                                              connected / unconfigured / failed / offline / unchecked
 * ```
 * 第二段以前散在页面里（`ModelsView.vue` 的 `STATUS_LABEL`），
 * 结果是**「离线」（本地服务没起）与「连接失败」（鉴权/超时/限流）被糊成同一个词「不可用」** ——
 * 信息在归约时就丢了，页面拿不到"为什么失败"。
 *
 * 本文件把第二段收成**唯一出处**，并且**零 IO / 零框架 / 零 import 运行期依赖** ——
 * 因此验收脚本可以把它编译成 JS 在 Node 里直接穷举（同 `ai/assistant/session.ts` 的手法）。
 *
 * ## 判据（顺序即优先级，逐条可证伪）
 *
 * | 事实 | 结论 | 理由 |
 * |------|------|------|
 * | `enabled=false` | `offline` | Provider 未开放（`web-ai` / `user-agent` 占位）或模型被停用 —— 谈不上连接 |
 * | 需要 key 但没有凭据 | `unconfigured` | 缺前提，**根本发不出请求**；不该报"失败" |
 * | 探测通过 | `connected` | 唯一由**真实请求**得出的正向结论 |
 * | 从没测过 | `unchecked` | 如实说"未测试"，**不猜**（猜出来的绿灯比红灯更有害） |
 * | 失败码 ∈ 离线类 | `offline` | 服务没起 / 不可达 → 用户该去启动服务 |
 * | 其余失败码 | `failed` | 鉴权 / 超时 / 限流 / 响应异常 → 用户该去查配置 |
 *
 * ⚠️ 词表**不引入新视觉**：5 个显示态映射到既有 3 个 dot 类（`pw-dot--ok/wait/off`），
 * 见 `components/ui/primitives.css`。UI 视觉体系不动。
 */

import type { ConnectionType } from './model'
import type { ModelEntryStatus } from './registry'

/** 显示态（唯一出处）。前四个是 TECH-06-A 点名要求的语义；`unchecked` 是如实保留的"未测试"。 */
export const DISPLAY_STATUSES = [
  'connected',
  'unconfigured',
  'failed',
  'offline',
  'unchecked',
] as const
export type DisplayStatus = (typeof DISPLAY_STATUSES)[number]

/**
 * 归为「离线」的失败码：**服务/进程不可达**。
 *
 * 与 Python `ProviderError` 码表同源（`provider.ts:67` `PROVIDER_ERROR_CODES`）。
 * 区分它和「连接失败」的意义：前者的处置动作是"把本地服务起起来"，
 * 后者是"检查 API Key / 网络 / 额度"——两个完全不同的动作，不该显示同一个词。
 */
export const OFFLINE_CODES: readonly string[] = ['local_model_down', 'unreachable']

/** 归约所需的事实（全部来自 `ModelListEntry`，不额外发请求）。 */
export interface StatusFacts {
  /** Provider 是否开放 / 模型是否启用。 */
  enabled: boolean
  /** 领域内部态（`entryStatusOf` 的产物）。 */
  entryStatus: ModelEntryStatus
  /** 该 Provider 是否需要 API Key（本地模型为 `false`）。 */
  needsSecret: boolean
  /** 是否已配置凭据（只问存在性，**不碰明文**）。 */
  hasSecret: boolean
  /** 最近一次探测的失败码（成功或无记录时为空串）。 */
  lastError: string
}

/**
 * 把「领域内部态 + 凭据 + 失败码」归约成唯一的显示态。**纯函数：同输入同输出。**
 */
export function displayStatusOf(f: StatusFacts): DisplayStatus {
  // ① 未开放 / 已停用：连"能否连接"都还不成立
  if (!f.enabled) return 'offline'
  if (f.entryStatus === 'disabled') return 'offline'

  // ② 缺前提：需要 key 却没有 → 请求根本发不出去（不是"连接失败"）
  if (f.needsSecret && !f.hasSecret) return 'unconfigured'

  // ③ 真实探测通过 —— 这是**唯一**能得出"已连接"的路径
  if (f.entryStatus === 'ready') return 'connected'

  // ④ 从没测过：如实显示"未测试"，不猜
  if (f.entryStatus === 'unchecked') return 'unchecked'

  // ⑤ 测过且失败：按失败码分流「离线」vs「连接失败」
  return OFFLINE_CODES.includes(f.lastError) ? 'offline' : 'failed'
}

/**
 * 显示态 → 文案 + dot 类。
 *
 * `hint` 是给用户看的"下一步该做什么"，**与判据同源**（不另写一套说法）。
 * 注意：这里只有文案，**没有 CSS**（复用既有 dot 类，UI 视觉不变）。
 */
export const DISPLAY_STATUS_META: Record<
  DisplayStatus,
  { dot: string; text: string; hint: string }
> = {
  connected: { dot: 'ok', text: '已连接', hint: '最近一次探测通过' },
  unconfigured: { dot: 'wait', text: '未配置', hint: '还缺凭据或必填项，尚未发起过探测' },
  failed: { dot: 'off', text: '连接失败', hint: '凭据 / 网络 / 额度有问题，详见最近测试' },
  offline: { dot: 'off', text: '离线', hint: '服务未启动或不可达；未开放的 Provider 也在这一类' },
  unchecked: { dot: 'wait', text: '未测试', hint: '还没探测过 —— 点「测试连接」拿真实结果' },
}

/** 显示态 → 文案（便利函数，避免调用方自己查表）。 */
export function statusTextOf(s: DisplayStatus): string {
  return DISPLAY_STATUS_META[s].text
}

/** 连接类型的展示名（与 `ModelsView.vue` 原有 `TYPE_LABEL` 同源，收拢到领域层）。 */
export const CONNECTION_TYPE_LABEL: Record<ConnectionType, string> = {
  api: 'API 模型',
  local: '本地模型',
  agent: '个人Agent',
}

/**
 * 探测结果的**人话结论**（`ConnectionTestResult` → 一句可核验的说明）。
 *
 * 关键：`probed === false` 表示"**没发请求就短路了**" ——
 * 这时绝不能显示"连接失败"，因为压根没连过。UI 文案必须区分这一点。
 */
export function probeConclusionOf(res: {
  ok: boolean
  probed: boolean
  code: string
  message: string
  modelCount: number
  ms: number
}): string {
  if (res.ok) return `已连接（${res.modelCount} 个可用模型 · ${res.ms} ms）`
  if (!res.probed) return `未发起探测：${res.message}`
  return `探测失败（${res.code}）：${res.message}`
}
