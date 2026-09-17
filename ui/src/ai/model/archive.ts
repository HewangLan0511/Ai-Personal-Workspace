/**
 * 模型清单归档（TECH-06-B Part 1）—— **唯一持久化来源** `ai.models.registry`
 *
 * ## 它解决什么
 * TECH-06-A 审计 §四登记的遗留项：`registry.list()` 只读内存 `store`，`hydrate()` 只灌
 * Provider / 凭据 / canonical —— **刷新 / 重启后"我的模型"为空**。
 *
 * ## 三条硬边界（来自 TECH-06-B 指令）
 * 1. **不新增 localStorage**：落点是 core config 键（SQLite `config` 表），
 *    走既有 `get_config` / `put_config` 命令（见 `ports.ts::coreArchivePort`）。
 * 2. **不产生第二事实源**：本文件只定义**序列化形态**；谁读谁写只有 `ModelRegistry` 一处
 *    （`hydrate()` 读，`add/update/remove/clear` 写）。页面 / AI 侧栏照旧只碰 Registry。
 * 3. **不破坏 ModelRegistry**：`add/update/remove` 的**同步签名不变** ——
 *    落盘是异步旁路（串行队列 + `archiveFlushed()`），调用方零改动。
 *
 * ## ⚠️ 刻意**不持久化**探测状态（反假绿，TECH-06-A 的核心纪律）
 *
 * `ModelStatus` 里的 `available / lastCheck / lastError` 是**本会话的探测结果**：
 * - 若把 `available: true` 存下来，重启后会**没发请求就显示「已连接」** ——
 *   这正是 TECH-06-A 用 288 组合穷举锁死的假绿（`①c`：非 ready ⇒ 不得 connected）。
 * - 若把 `lastError` 存下来，重启后会显示上一次会话的「离线 / 连接失败」——
 *   用户看到的是**陈旧的红**，同样不可信。
 *
 * 所以归档记录**结构上就没有**这三个字段（见 `ArchiveRecord`），恢复时一律
 * `available: false`、无 `lastError` → 如实显示「未测试」，等用户/系统重新探测。
 * 已持久化的只有**用户意图**（enabled）与**身份配置**（provider/model/connection/能力/时间戳）。
 *
 * ## 容错（宁可降级，不可崩掉启动）
 * - 归档串损坏 → **不抛错**，逐条丢弃 + 记 issue（`parseArchive`）。
 * - 读不到（core 不可达）→ Registry **拒绝覆盖写**（fail-closed，见 `registry.ts`），
 *   避免"读不到就把空列表写回去"造成静默清库。
 */

import {
  defaultCapabilities,
  emptyStatus,
  newMetadata,
  validateModelProfile,
  type ModelCapabilities,
  type ModelConnection,
  type ModelProfile,
} from './model'

// ---------------------------------------------------------------- 键与版本

/**
 * 归档键（core `config` 表）。**契约键**：登记在 `core/src/db/config.rs` 的 `KEYS`
 * （TECH-06-B，契约 v13）。类型 `string`（存 JSON），与 `widget.desktop.config` /
 * `profile.rejected_kinds` 的既有同构约定一致。
 */
export const ARCHIVE_KEY = 'ai.models.registry'

/** 归档格式版本。字段形态变化时 +1，读取端据此拒绝旧格式而不是猜。 */
export const ARCHIVE_VERSION = 1

// ---------------------------------------------------------------- 记录形态

/** 一条归档记录 = `ModelProfile` **去掉探测状态**、加上显式 `enabled`。 */
export interface ArchiveRecord {
  id: string
  provider: string
  name: string
  model: string
  connection: ModelConnection
  capabilities: ModelCapabilities
  /** 用户意图（是否启用）。**唯一**被持久化的 status 语义。 */
  enabled: boolean
  createdAt: number
  updatedAt: number
  /** 前向兼容扩展位（原样透传，读取端不解释）。 */
  extras?: Record<string, unknown>
}

interface ArchiveEnvelope {
  v: number
  models: ArchiveRecord[]
}

export interface ArchiveIssue {
  /** 出问题的位置（第几条 / 哪个字段），便于在 UI / 日志里定位。 */
  at: string
  message: string
}

export interface ParsedArchive {
  models: ArchiveRecord[]
  issues: ArchiveIssue[]
}

// ---------------------------------------------------------------- 序列化

/** 取"应该被持久化的那一半"。**探测状态在这里被刻意丢掉**（见文件头说明）。 */
function toRecord(p: ModelProfile): ArchiveRecord {
  const rec: ArchiveRecord = {
    id: p.id,
    provider: p.provider,
    name: p.name,
    model: p.model,
    connection: { ...p.connection },
    capabilities: { ...p.capabilities },
    enabled: p.status.enabled,
    createdAt: p.metadata.createdAt,
    updatedAt: p.metadata.updatedAt,
  }
  if (p.metadata.extras !== undefined) {
    try {
      rec.extras = JSON.parse(JSON.stringify(p.metadata.extras)) as Record<string, unknown>
    } catch {
      /* 不可克隆的 extras 丢弃 —— 归档不能因为扩展位挂掉 */
    }
  }
  return rec
}

/**
 * 把当前模型清单序列化成归档串。
 *
 * **确定性**：按 `id` 排序后输出 —— 同一份内存状态永远得到字节级相同的串，
 * 这样"写没写成功 / 写的是不是这份"可以用字符串相等来断言（验收与排障都靠它）。
 */
export function serializeArchive(profiles: readonly ModelProfile[]): string {
  const models = [...profiles]
    .map(toRecord)
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  const envelope: ArchiveEnvelope = { v: ARCHIVE_VERSION, models }
  return JSON.stringify(envelope)
}

// ---------------------------------------------------------------- 解析

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 单条记录的宽松取串（容忍 null / 数字 / 缺失），空值返回 null 由调用方决定丢弃。 */
function asString(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v : null
}

/**
 * 解析归档串。**永不抛错** —— 损坏的归档不能把启动打挂。
 *
 * 逐条独立校验：坏一条丢一条（记 issue），好的一条不丢。
 */
export function parseArchive(raw: string): ParsedArchive {
  const issues: ArchiveIssue[] = []
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return { models: [], issues } // 空串 = 从未写过，不是错误

  let env: unknown
  try {
    env = JSON.parse(trimmed)
  } catch {
    return { models: [], issues: [{ at: '<root>', message: '归档不是合法 JSON（已按空清单处理）' }] }
  }
  if (!isPlainObject(env)) {
    return { models: [], issues: [{ at: '<root>', message: '归档顶层不是对象（已按空清单处理）' }] }
  }

  const v = env.v
  if (v !== ARCHIVE_VERSION) {
    return {
      models: [],
      issues: [
        {
          at: 'v',
          message: `归档格式版本不识别：${String(v)}（当前 ${ARCHIVE_VERSION}，已按空清单处理，不猜）`,
        },
      ],
    }
  }
  if (!Array.isArray(env.models)) {
    return { models: [], issues: [{ at: 'models', message: '归档缺少 models 数组（已按空清单处理）' }] }
  }

  const seen = new Set<string>()
  const models: ArchiveRecord[] = []
  env.models.forEach((item, i) => {
    const at = `models[${i}]`
    if (!isPlainObject(item)) {
      issues.push({ at, message: '记录不是对象，已丢弃' })
      return
    }
    const id = asString(item.id)
    const provider = asString(item.provider)
    const model = asString(item.model)
    if (!id || !provider || !model) {
      issues.push({ at, message: `缺少 id/provider/model，已丢弃（id=${String(item.id)}）` })
      return
    }
    if (seen.has(id)) {
      issues.push({ at, message: `重复 id「${id}」，保留首条` })
      return
    }
    // connection / capabilities 缺失时给最小占位，真正的结构校验交给 materialize
    const connection = isPlainObject(item.connection)
      ? (item.connection as unknown as ModelConnection)
      : { type: 'api' as const }
    const capabilities = isPlainObject(item.capabilities)
      ? (item.capabilities as unknown as ModelCapabilities)
      : defaultCapabilities()
    const createdAt = typeof item.createdAt === 'number' ? item.createdAt : 0
    const updatedAt = typeof item.updatedAt === 'number' ? item.updatedAt : createdAt
    const rec: ArchiveRecord = {
      id,
      provider,
      name: asString(item.name) ?? model,
      model,
      connection,
      capabilities,
      enabled: item.enabled === false ? false : true, // 只认显式 false；缺省/乱值一律按"启用"
      createdAt,
      updatedAt,
    }
    if (isPlainObject(item.extras)) rec.extras = item.extras
    seen.add(id)
    models.push(rec)
  })

  return { models, issues }
}

// ---------------------------------------------------------------- 物化

export interface Materialized {
  profile?: ModelProfile
  error?: string
}

/**
 * 归档记录 → 可入注册表的 `ModelProfile`。
 *
 * **关键：这是"恢复"，不是"新增"** —— 不查 Provider 表、不补缺省端点、不看凭据。
 * 原因：恢复时 core 可能不可达（`loadProviders()` 返回空），若要求 Provider 在册，
 * 就会出现"core 一掉线 → 恢复失败 → 下次落盘把空清单写回去"的**静默清库**。
 * 未知的 Provider 照样恢复，`ModelListEntry` 的 `needsSecret` 会走保守兜底
 * （`registry.ts::list()`：`desc ? desc.needsKey : p.connection.type === 'api'`），
 * UI 侧如实显示，不猜。
 *
 * **探测状态恒为「未测过」**：`available: false`、无 `lastError`（见文件头的反假绿说明）。
 */
export function materializeArchiveRecord(rec: ArchiveRecord, now: number): Materialized {
  const draft = {
    id: rec.id,
    provider: rec.provider,
    name: rec.name,
    model: rec.model,
    connection: rec.connection,
    capabilities: rec.capabilities,
    // ★ 反假绿：恢复出来的模型一律"未测试"，等真实探测给结论
    status: emptyStatus({ enabled: rec.enabled, available: false }),
    metadata: newMetadata(now),
  }
  // metadata 的时间戳来自归档（ createdAt 是模型的真实年龄，不该被重启改写）
  draft.metadata.createdAt = rec.createdAt || now
  draft.metadata.updatedAt = rec.updatedAt || now
  if (rec.extras !== undefined) draft.metadata.extras = rec.extras

  const res = validateModelProfile(draft)
  if (!res.ok || !res.value) {
    const brief = res.issues
      .slice(0, 3)
      .map((i) => `${i.path}(${i.code})`)
      .join(', ')
    return { error: `记录「${rec.id}」未通过结构校验，已丢弃：${brief}` }
  }
  return { profile: res.value }
}
