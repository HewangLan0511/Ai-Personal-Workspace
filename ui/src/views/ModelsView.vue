<script setup lang="ts">
/**
 * 模型管理中心（TECH-05-C §P0-1）。
 *
 * 路由 `/models`。**不进主导航**（原型 UI-06 的定位：设置 → AI 与模型；
 * 不抢 AI 助手的入口），返回按钮按 `?from=ai|settings` 回到来源。
 *
 * ## 数据来源：唯一 = ModelRegistry
 * ```
 *   registry = bridge.getSharedRegistry()        ← 全应用同一个实例
 *     ├─ list()            → "我的模型" 网格
 *     ├─ resolveCurrentModel()  → "当前模型" 卡（与 AI 侧栏**同一个投影函数**）
 *     ├─ listProviders()   → 添加抽屉里的 Provider 选项 + 展示名
 *     ├─ add() / remove()  → 新增 / 删除
 *     ├─ check()           → 测试连接
 *     ├─ setDefault()      → 「设为默认」
 *     └─ subscribe()       → 任何变更（含 canonical）后刷新本页
 *   bridge.syncSelection()  → 「切换模型」（与 AI 侧栏 setProvider/setModel 同一个写口）
 * ```
 * 因此「本页显示的当前模型」与「AI 请求实际使用的 currentModel」**结构上同源**：
 * 两者都读同一份 canonical；本页切一次，AI 侧栏（`useCurrentModel`）立刻跟着变。
 *
 * ## 明确没做的事（P0-1 禁止项）
 * - 没有第二份模型清单：不定义 MODELS / 不定义 aiModel / 不把列表写进 localStorage；
 * - 模型列表**不是**本页的 state：`models` 只是 `registry.list()` 的一次投影，
 *   任何写操作后由 `registry.subscribe()` 触发重取 —— 页面不维护、不拼接；
 * - 凭据（API Key）**不在本页输入**：全应用只有「设置 → AI」一处密钥面
 *   （`settings` 已接 `ai_info` / 凭据库），本页只显示"是否已配置"并提供跳转，
 *   避免出现第二个存密钥的地方。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  ensureHydrated,
  getSharedRegistry,
  syncSelection,
} from '@/ai/model/bridge'
import { resolveCurrentModel } from '@/ai/model/consumer'
import type { ConnectionType } from '@/ai/model/model'
import type { ConnectionTestResult, ProviderDescriptor } from '@/ai/model/provider'
import type { ModelListEntry } from '@/ai/model/registry'
import {
  CONNECTION_TYPE_LABEL,
  DISPLAY_STATUS_META,
  displayStatusOf,
  probeConclusionOf,
  type DisplayStatus,
} from '@/ai/model/status'
import PwButton from '@/components/ui/PwButton.vue'
import PwCard from '@/components/ui/PwCard.vue'
import PwChip from '@/components/ui/PwChip.vue'
import PwDrawer from '@/components/ui/PwDrawer.vue'
import { toast } from '@/composables/useToast'

const router = useRouter()
const route = useRoute()

/** 全应用唯一的 ModelRegistry（显示与调用共用同一实例）。 */
const registry = getSharedRegistry()

// ---------------------------------------------------------------- 读模型

/** `list()` 的投影。**不是**本页自己维护的清单 —— 每次变更后重建。 */
const models = ref<ModelListEntry[]>([])
const providers = ref<ProviderDescriptor[]>([])
const hydrated = ref(false)

/** 最近一次「测试连接」的结果（UI 瞬时态；不落库、不是业务状态）。 */
const probes = reactive<Record<string, ConnectionTestResult>>({})

function refresh(): void {
  models.value = registry.list()
  providers.value = registry.listProviders()
}

/** 「当前模型」——与 AI 侧栏共用 `resolveCurrentModel()`，不另写一份投影逻辑。 */
const currentView = computed(() => resolveCurrentModel(registry))
/** 当前 canonical 的 provider/model（给验收脚本直接读，见 data-pw-* 属性）。 */
const currentKey = computed(() => {
  const c = currentView.value.canonical
  return c.model ? `${c.provider}::${c.model}` : ''
})

/**
 * 页面内验收句柄（与 `window.__pwMotion` / `window.__pwWorkspace` 同源做法）。
 *
 * 存在的意义：让"本页显示的当前模型"与"AI 请求实际使用的当前模型"能**在同一页里
 * 被机器比对** —— 脚本读 `__pwModels.registry.getDefault()`（本页取数的那份真相），
 * 再读 AI 侧栏 `.ai-canonical-val`（`useCurrentModel` 的投影），两者必须一致。
 * 只暴露已经存在的 Registry 与一个纯读函数，不新增任何写口。
 */
declare global {
  interface Window {
    __pwModels?: {
      registry: typeof registry
      current: () => string
      /**
       * Registry 的**真实状态**逐项输出（TECH-06-A）。
       *
       * 存在的意义：让"页面显示的状态"与"Registry 的真实状态"能在同一页里被机器比对 ——
       * 脚本读本函数（真相），再读 DOM 的 `[data-pw-model-status]`（显示），两者必须一致。
       * 只读：不写任何状态、不发任何请求。
       */
      statuses: () => Array<{
        id: string
        display: DisplayStatus
        entryStatus: ModelListEntry['status']
        lastError: string
        needsSecret: boolean
        hasSecret: boolean
        enabled: boolean
      }>
      /** 触发一次真实探测（与页面按钮走同一条 `registry.check()`）。 */
      probe: (id: string) => Promise<ConnectionTestResult>
      /**
       * 纯函数直通（验收/排障用）：把任意事实喂给**出厂包里的**归约函数。
       *
       * 为什么需要：本环境（无 core）模型列表为空，"DOM == Registry" 会空转。
       * 有了它，脚本可以先用 `add()` 造一个真实模型、再 `probe()` 触发真实失败，
       * 从而对**最终产物**做出非空转的断言。**只读**：不改任何状态、不发请求。
       */
      statusOf: (facts: {
        enabled: boolean
        entryStatus: ModelListEntry['status']
        needsSecret: boolean
        hasSecret: boolean
        lastError: string
      }) => DisplayStatus
    }
  }
}

if (typeof window !== 'undefined') {
  window.__pwModels = {
    registry,
    current: () => currentKey.value,
    statuses: () =>
      registry.list().map((e) => ({
        id: e.id,
        display: statusKey(e),
        entryStatus: e.status,
        lastError: e.lastError,
        needsSecret: e.needsSecret,
        hasSecret: e.hasSecret,
        enabled: e.enabled,
      })),
    probe: (id: string) => registry.check(id),
    statusOf: (facts) => displayStatusOf(facts),
  }
}

let unsubscribe: (() => void) | null = null

onMounted(async () => {
  unsubscribe = registry.subscribe(() => {
    refresh()
  })
  refresh()
  await ensureHydrated()
  hydrated.value = true
  refresh()
})

onUnmounted(() => {
  unsubscribe?.()
  unsubscribe = null
})

// ---------------------------------------------------------------- 展示映射

/** 连接类型展示名：**取自领域层**（`ai/model/status.ts`），页面不再自己抄一份。 */
const TYPE_LABEL = CONNECTION_TYPE_LABEL

/**
 * 状态 → 显示态：**唯一判据在领域层**（`displayStatusOf`，纯函数、Node 可穷举）。
 *
 * 本页只做一件事：把 `ModelListEntry` 的**真实事实**喂进去。
 * 页面**没有**第二套判断 —— 没有 `lastError ? '不可用' : …` 这种就地三元。
 */
function statusKey(entry: ModelListEntry): DisplayStatus {
  return displayStatusOf({
    enabled: entry.enabled,
    entryStatus: entry.status,
    needsSecret: entry.needsSecret,
    hasSecret: entry.hasSecret,
    lastError: entry.lastError,
  })
}

/** 显示态的 dot 类与文案（复用既有 3 个 dot 类，不新增样式）。 */
function statusMeta(entry: ModelListEntry) {
  return DISPLAY_STATUS_META[statusKey(entry)]
}

function providerLabel(id: string): string {
  const d = providers.value.find((p) => p.id === id)
  return d?.label || id || '（未知 Provider）'
}

function typeOf(entry: ModelListEntry): ConnectionType {
  return entry.connectionType
}

function msOf(id: string): string {
  const r = probes[id]
  if (!r) return ''
  return r.ok ? `${r.ms} ms` : '—'
}

/** 最近一次探测的"人话结论"（区分"没发请求就短路"与"真的探测失败"）。 */
function viewConclusion(): string {
  const r = viewProbe.value
  if (!r) return ''
  return probeConclusionOf(r)
}

/** 最近测试时间（来自 Registry 的真实事实，不是页面本地时钟）。 */
function lastCheckText(entry: ModelListEntry): string {
  if (!entry.lastCheck) return '从未测试'
  return new Date(entry.lastCheck).toLocaleString()
}

const countText = computed(() =>
  models.value.length ? `${models.value.length} 个模型` : '暂无模型',
)

/** Provider 是否已配凭据 —— 判据来自领域层事实（`needsSecret` / `hasSecret`），不另查 Provider 表。 */
function needsKeyAndMissing(entry: ModelListEntry): boolean {
  return entry.needsSecret && !entry.hasSecret
}

function describeError(e: unknown): string {
  const anyE = e as { issues?: { message?: string }[]; message?: string }
  if (Array.isArray(anyE?.issues) && anyE.issues.length) {
    return anyE.issues.map((i) => i.message ?? '').filter(Boolean).join('；')
  }
  return anyE?.message ?? String(e)
}

// ---------------------------------------------------------------- 抽屉状态

type Drawer = '' | 'switch' | 'view' | 'add' | 'avatar'
const drawer = ref<Drawer>('')
const busy = ref(false)

/** 查看：当前打开的模型 id。 */
const viewId = ref('')
const viewEntry = computed(() => models.value.find((m) => m.id === viewId.value) ?? null)
/** 该模型的最近一次探测结果（无则 null）——避免模板里做二次索引。 */
const viewProbe = computed<ConnectionTestResult | null>(() =>
  viewId.value ? probes[viewId.value] ?? null : null,
)

/** 连接类型枚举（模板里不写断言）。 */
const TYPES: ConnectionType[] = ['api', 'local', 'agent']

function openSwitch(): void {
  drawer.value = 'switch'
}

function openView(id: string): void {
  viewId.value = id
  drawer.value = 'view'
}

function closeDrawer(): void {
  drawer.value = ''
}

function goBack(): void {
  const from = String(route.query.from ?? 'settings')
  void router.push(from === 'ai' ? '/ai' : '/settings')
}

// ---- 添加抽屉（两步：选类型 → 填配置）--------------------------------

const draft = reactive<{
  type: ConnectionType | null
  provider: string
  name: string
  model: string
  endpoint: string
}>({ type: null, provider: '', name: '', model: '', endpoint: '' })

const providersOfType = computed(() =>
  draft.type ? providers.value.filter((p) => p.connectionType === draft.type && p.enabled) : [],
)

/** 哪些类型至少有一个可用 Provider（决定类型格是否可点）。 */
function typeAvailable(t: ConnectionType): boolean {
  return providers.value.some((p) => p.connectionType === t && p.enabled)
}

function openAdd(): void {
  draft.type = null
  draft.provider = ''
  draft.name = ''
  draft.model = ''
  draft.endpoint = ''
  drawer.value = 'add'
}

function pickType(t: ConnectionType): void {
  draft.type = t
  const first = providersOfType.value[0]
  selectProvider(first ? first.id : '')
}

function selectProvider(id: string): void {
  draft.provider = id
  const d = providers.value.find((p) => p.id === id)
  draft.endpoint = d?.defaultEndpoint ?? ''
  if (d && !draft.model) draft.model = d.defaultModel
}

const addReady = computed(() => !!draft.provider && !!draft.model.trim())

async function submitAdd(): Promise<void> {
  if (!addReady.value || busy.value) return
  busy.value = true
  try {
    registry.add({
      provider: draft.provider,
      name: draft.name.trim() || undefined,
      model: draft.model.trim(),
      ...(draft.type ? { connectionType: draft.type } : {}),
      ...(draft.endpoint.trim() ? { connection: { endpoint: draft.endpoint.trim() } } : {}),
    })
    toast.success('模型已添加')
    closeDrawer()
  } catch (e) {
    toast.error(describeError(e))
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------- 写操作

/** 「切换模型」——与 AI 侧栏同一处写口（界面选择 → canonical）。 */
async function switchTo(entry: ModelListEntry): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const snap = await syncSelection({
      provider: entry.provider,
      model: entry.model,
      apiBase: providers.value.find((p) => p.id === entry.provider)?.defaultEndpoint ?? '',
    })
    if (!snap) {
      toast.error('该 Provider 尚未开放，无法切换')
      return
    }
    closeDrawer()
    toast.success(`已切换到 ${entry.name || entry.model}`)
  } catch (e) {
    toast.error(describeError(e))
  } finally {
    busy.value = false
  }
}

/** 「设为默认」——Registry 为此设计的方法（写 canonical，唯一事实来源）。 */
async function makeDefault(entry: ModelListEntry): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await registry.setDefault(entry.id)
    toast.success(`${entry.name || entry.model} 已设为默认模型`)
  } catch (e) {
    toast.error(describeError(e))
  } finally {
    busy.value = false
  }
}

async function testConnection(entry: ModelListEntry): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const res = await registry.check(entry.id)
    probes[entry.id] = res
    if (res.ok) toast.success(`连接正常（${res.modelCount} 个可用模型 · ${res.ms} ms）`)
    else toast.error(res.message || res.code)
  } catch (e) {
    toast.error(describeError(e))
  } finally {
    busy.value = false
  }
}

function removeModel(entry: ModelListEntry): void {
  const label = entry.name || entry.model
  if (!window.confirm(`删除模型「${label}」？（凭据与其它模型不受影响）`)) return
  const ok = registry.remove(entry.id)
  if (ok) toast.info(`已删除 ${label}`)
  else toast.error('模型不存在（可能已被删除）')
}
</script>

<template>
  <section class="models-view">
    <header class="mv-head">
      <button type="button" class="pw-btn pw-btn--icon" title="返回" @click="goBack">←</button>
      <div class="pw-grow">
        <h2 class="pw-t-page">模型管理</h2>
        <p class="pw-t-cap">工作台的模型控制中心 · 连接、测试与切换，技术细节都替你收好了</p>
      </div>
      <PwButton variant="primary" @click="openAdd">＋ 添加模型</PwButton>
    </header>

    <!-- 当前模型：与 AI 侧栏共用同一个 canonical 投影 -->
    <PwCard
      size="lg"
      class="mv-current"
      data-pw-models-current
      :data-current-key="currentKey"
      :data-current-provider="currentView.canonical.provider"
      :data-current-model="currentView.canonical.model"
      :data-current-label="currentView.label"
    >
      <div class="pw-t-label">当前模型</div>
      <div class="pw-row pw-row--wrap mv-current-row">
        <span class="pw-avatar pw-avatar--lg">✦</span>
        <div class="pw-grow">
          <div class="pw-t-card">{{ currentView.label }}</div>
          <div class="pw-row pw-row--wrap mv-current-meta">
            <PwChip v-if="currentView.set" size="sm">{{ currentView.detail }}</PwChip>
            <PwChip v-if="currentView.badge" size="sm" variant="outline">
              {{ currentView.badge }}
            </PwChip>
            <span class="pw-t-cap">{{ currentView.title }}</span>
          </div>
        </div>
        <PwButton variant="primary" :disabled="models.length === 0" @click="openSwitch">
          切换模型
        </PwButton>
      </div>
    </PwCard>

    <div class="pw-row mv-sec-head">
      <div class="pw-t-section pw-grow">我的模型</div>
      <span class="pw-t-cap" data-pw-models-count>{{ countText }}</span>
    </div>

    <p v-if="!providers.length" class="pw-t-cap mv-note">
      核心服务未连接 —— 暂时读不到系统里可用的 Provider，添加模型会不可用（不影响已保存的模型）。
    </p>

    <div class="pw-grid pw-grid--models" data-pw-models-grid>
      <!-- 空态 -->
      <PwCard v-if="models.length === 0" variant="ghost" class="mv-empty">
        <span class="pw-avatar pw-avatar--lg">✦</span>
        <div class="pw-t-card">还没有添加模型</div>
        <div class="pw-t-cap">连接一个 AI 模型，让工作台拥有自己的智能</div>
        <PwButton variant="primary" size="sm" :disabled="!providers.length" @click="openAdd">
          ＋ 添加模型
        </PwButton>
      </PwCard>

      <PwCard
        v-for="m in models"
        :key="m.id"
        stack
        class="mv-card"
        :data-model-id="m.id"
        :data-pw-model-id="m.id"
        :data-pw-model-status="statusKey(m)"
        :data-pw-model-entry-status="m.status"
      >
        <div class="pw-row pw-row--top">
          <div class="pw-grow">
            <div class="pw-t-card">{{ m.name || m.model }}</div>
            <div class="pw-t-cap mv-card-sub">
              {{ providerLabel(m.provider) }}<template v-if="m.model"> · {{ m.model }}</template>
              · {{ TYPE_LABEL[typeOf(m)] }}
            </div>
          </div>
          <PwChip v-if="m.isDefault" size="sm" variant="brand" data-pw-is-default>当前</PwChip>
        </div>

        <div class="pw-row pw-row--wrap">
          <PwChip size="sm">
            <i class="pw-dot" :class="`pw-dot--${statusMeta(m).dot}`"></i>
            {{ statusMeta(m).text }}
          </PwChip>
          <PwChip v-if="msOf(m.id)" size="sm" class="pw-mono">{{ msOf(m.id) }}</PwChip>
          <PwChip v-if="needsKeyAndMissing(m)" size="sm" variant="outline">未配密钥</PwChip>
        </div>

        <div class="pw-row pw-row--wrap mv-card-foot">
          <PwButton size="sm" variant="secondary" @click="openView(m.id)">查看</PwButton>
          <PwButton
            v-if="!m.isDefault"
            size="sm"
            variant="secondary"
            :disabled="busy"
            @click="makeDefault(m)"
          >
            设为默认
          </PwButton>
          <PwButton size="sm" variant="secondary" :disabled="busy" @click="testConnection(m)">
            测试连接
          </PwButton>
          <PwButton size="sm" variant="danger" :disabled="busy" @click="removeModel(m)">
            删除
          </PwButton>
        </div>
      </PwCard>
    </div>

    <button
      v-if="models.length > 0"
      type="button"
      class="mv-add-row"
      :disabled="!providers.length"
      @click="openAdd"
    >
      <span class="mv-add-icon">＋</span>
      <span class="pw-t-sm mv-add-title">添加模型</span>
      <span class="pw-t-cap">API · 本地 · 个人 Agent</span>
    </button>

    <!-- ---------------------------------------------------- 切换模型 -->
    <PwDrawer :open="drawer === 'switch'" title="切换模型" aria-label="切换模型" @close="closeDrawer">
      <p class="pw-t-cap mv-hint">切换立即生效，聊天与工作空间助手都会使用它。</p>
      <button
        v-for="m in models"
        :key="m.id"
        type="button"
        class="pw-row-item"
        :disabled="busy"
        @click="switchTo(m)"
      >
        <span class="pw-row-item__main">
          <span class="pw-row-item__title">{{ m.name || m.model }}</span>
          <span class="pw-t-cap mv-block">{{ providerLabel(m.provider) }}</span>
        </span>
        <PwChip v-if="m.isDefault" size="sm" variant="brand">当前</PwChip>
        <PwChip v-else size="sm">
          <i class="pw-dot" :class="`pw-dot--${statusMeta(m).dot}`"></i>
          {{ statusMeta(m).text }}
        </PwChip>
      </button>
      <p v-if="models.length === 0" class="pw-t-cap">还没有可切换的模型，先添加一个吧</p>
      <template #foot>
        <PwButton variant="ghost" @click="openAdd">＋ 添加模型</PwButton>
        <span class="pw-spacer"></span>
        <PwButton variant="primary" @click="closeDrawer">完成</PwButton>
      </template>
    </PwDrawer>

    <!-- ---------------------------------------------------- 查看模型 -->
    <PwDrawer
      :open="drawer === 'view'"
      :title="viewEntry ? viewEntry.name || viewEntry.model : '模型'"
      aria-label="查看模型"
      @close="closeDrawer"
    >
      <template v-if="viewEntry">
        <div class="pw-row pw-row--wrap mv-drawer-chips">
          <PwChip size="sm">{{ TYPE_LABEL[typeOf(viewEntry)] }}</PwChip>
          <PwChip size="sm">
            <i class="pw-dot" :class="`pw-dot--${statusMeta(viewEntry).dot}`"></i>
            {{ statusMeta(viewEntry).text }}
          </PwChip>
          <PwChip v-if="viewProbe" size="sm" class="pw-mono">{{ viewProbe.ms }} ms</PwChip>
          <PwChip v-if="viewEntry.isDefault" size="sm" variant="brand">当前</PwChip>
        </div>

        <dl class="mv-kv">
          <div class="mv-kv-row">
            <dt class="pw-t-cap">展示名</dt>
            <dd class="pw-t-sm">{{ viewEntry.name || '—' }}</dd>
          </div>
          <div class="mv-kv-row">
            <dt class="pw-t-cap">Provider</dt>
            <dd class="pw-t-sm">{{ providerLabel(viewEntry.provider) }}</dd>
          </div>
          <div class="mv-kv-row">
            <dt class="pw-t-cap">模型名</dt>
            <dd class="pw-t-sm pw-mono mv-ellipsis">{{ viewEntry.model }}</dd>
          </div>
          <div class="mv-kv-row">
            <dt class="pw-t-cap">凭据</dt>
            <dd class="pw-t-sm">
              {{ viewEntry.hasSecret ? '已配置' : '未配置' }}
              <span class="pw-t-cap">（密钥只在「设置 → AI」中填写）</span>
            </dd>
          </div>
          <div class="mv-kv-row">
            <dt class="pw-t-cap">最近测试</dt>
            <dd class="pw-t-sm">
              <template v-if="viewProbe">{{ viewConclusion() }}</template>
              <template v-else>本次会话尚未测试</template>
              <span class="pw-t-cap"> · Registry 记录：{{ lastCheckText(viewEntry) }}</span>
            </dd>
          </div>
        </dl>

        <PwCard variant="ghost" class="mv-info">
          <span class="pw-t-sm pw-c2">
            状态与耗时来自真实连通性探测：代码没有配好凭据或本地服务未启动时，这里会如实报失败，
            不会显示一个假的"已连接"。<br />
            「离线」= 服务没起或不可达；「连接失败」= 鉴权 / 超时 / 额度问题 —— 两者的处置动作不同，
            所以不合并成一个词。「未配置」= 压根发不出请求，不算失败。
          </span>
        </PwCard>
      </template>
      <template #foot>
        <PwButton
          variant="secondary"
          :disabled="busy || !viewEntry"
          @click="viewEntry && testConnection(viewEntry)"
        >
          测试连接
        </PwButton>
        <span class="pw-spacer"></span>
        <PwButton variant="primary" @click="closeDrawer">完成</PwButton>
      </template>
    </PwDrawer>

    <!-- ---------------------------------------------------- 添加模型 -->
    <PwDrawer :open="drawer === 'add'" title="添加模型" aria-label="添加模型" @close="closeDrawer">
      <template v-if="!draft.type">
        <p class="pw-t-cap mv-hint">要添加哪一种？</p>
        <div class="pw-grid mv-pick-grid">
          <button
            v-for="t in TYPES"
            :key="t"
            type="button"
            class="mv-pick"
            :disabled="!typeAvailable(t)"
            @click="pickType(t)"
          >
            <span class="mv-pick-em">{{ t === 'api' ? '🌐' : t === 'local' ? '💻' : '🤖' }}</span>
            <span class="pw-t-card">{{ TYPE_LABEL[t] }}</span>
            <span class="pw-t-cap">
              {{
                t === 'api'
                  ? '连接云端服务，如 OpenAI'
                  : t === 'local'
                    ? '运行在自己的电脑上'
                    : '你的个人 Agent'
              }}
            </span>
          </button>
        </div>
        <p v-if="!providers.length" class="pw-t-cap mv-hint">
          核心服务未连接，暂时拿不到可用的 Provider（这与"没有模型"是两件事）。
        </p>
      </template>

      <template v-else>
        <div class="pw-row pw-row--wrap mv-hint">
          <PwChip
            v-for="t in TYPES"
            :key="t"
            :as="'button'"
            :variant="draft.type === t ? 'brand' : 'default'"
            :disabled="!typeAvailable(t)"
            @click="pickType(t)"
          >
            {{ TYPE_LABEL[t] }}
          </PwChip>
        </div>

        <div class="pw-field mv-field">
          <label>Provider</label>
          <div class="pw-input pw-input--lg">
            <select
              :value="draft.provider"
              class="mv-select"
              @change="selectProvider(($event.target as HTMLSelectElement).value)"
            >
              <option v-for="p in providersOfType" :key="p.id" :value="p.id">
                {{ p.label }}{{ p.needsKey ? '' : '（无需密钥）' }}
              </option>
            </select>
          </div>
        </div>

        <div class="pw-field mv-field">
          <label>名称（在工作台里显示）</label>
          <div class="pw-input pw-input--lg">
            <input v-model="draft.name" placeholder="例如：GPT-5" />
          </div>
        </div>

        <div class="pw-field mv-field">
          <label>模型名称</label>
          <div class="pw-input pw-input--lg">
            <input v-model="draft.model" class="pw-mono" placeholder="例如：deepseek-chat" />
          </div>
        </div>

        <div v-if="draft.type !== 'agent'" class="pw-field mv-field">
          <label>{{ draft.type === 'local' ? '服务地址' : '服务地址 Endpoint' }}</label>
          <div class="pw-input pw-input--lg">
            <input
              v-model="draft.endpoint"
              class="pw-mono"
              placeholder="https://… 或 http://127.0.0.1:11434"
            />
          </div>
        </div>

        <PwCard variant="ghost" class="mv-info">
          <span class="pw-t-sm pw-c2">
            这里不填写密钥 —— 全应用只有「设置 → AI」一处密钥面，避免出现第二个存密钥的地方。
            添加后若提示"未配密钥"，去设置页填一次即可，同 Provider 的所有模型共用。
          </span>
        </PwCard>
      </template>

      <template #foot>
        <PwButton v-if="draft.type" variant="ghost" @click="draft.type = null">重新选择</PwButton>
        <span class="pw-spacer"></span>
        <PwButton v-if="draft.type" variant="primary" :disabled="!addReady || busy" @click="submitAdd">
          添加
        </PwButton>
        <PwButton v-else variant="secondary" @click="closeDrawer">取消</PwButton>
      </template>
    </PwDrawer>
  </section>
</template>

<style scoped>
/* 只做**本页版面**（间距/流式布局）。所有外观值（色/圆角/阴影/内距）
   一律来自共享原语与 token —— 本页不定义任何裸色值、不新增动画。 */
.models-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.mv-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mv-current-row {
  gap: 16px;
  margin-top: 8px;
}

.mv-current-meta {
  gap: 8px;
  margin-top: 4px;
}

.mv-sec-head {
  justify-content: space-between;
  margin-top: 4px;
}

.mv-note {
  margin: 0;
}

.mv-card-sub {
  margin-top: 2px;
}

.mv-card-foot {
  gap: 4px;
  margin-top: 4px;
}

.mv-empty {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 16px;
  text-align: center;
}

.mv-add-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  margin-top: 4px;
  padding: 12px 16px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-card);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}

.mv-add-row:hover:not(:disabled) {
  background: var(--surface-2);
}

.mv-add-row:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mv-add-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: var(--f-radius-2);
  background: var(--surface-3);
}

.mv-add-title {
  font-weight: 600;
}

.mv-hint {
  margin: 0 0 12px;
}

.mv-block {
  display: block;
}

.mv-field {
  margin-bottom: 12px;
}

.mv-select {
  flex: 1;
  min-width: 0;
  border: 0;
  background: none;
  outline: 0;
  padding: 0;
  border-radius: 0;
  font-size: 13px;
  color: var(--text-1);
}

.mv-pick-grid {
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
}

.mv-pick {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
  background: var(--surface-1);
  text-align: left;
  cursor: pointer;
}

.mv-pick:hover:not(:disabled) {
  border-color: var(--brand-500);
}

.mv-pick:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.mv-pick-em {
  font-size: 20px;
}

.mv-drawer-chips {
  gap: 8px;
  margin-bottom: 16px;
}

.mv-kv {
  margin: 0;
}

.mv-kv-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.mv-kv-row dd {
  margin: 0;
}

.mv-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mv-info {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
</style>
