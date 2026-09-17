/**
 * 当前模型（只读）—— TECH-03-B · TASK-04 的 UI 接线点。
 *
 * ## 它做什么
 * 把 `ModelRegistry` 的 canonical 投影成一个响应式的"当前模型"读模型，
 * 供 AI 侧栏顶部展示。**只读**：本 composable 不暴露任何写方法，
 * 也不会去调 `check()`（不连真实 API）、不会写 config、不会碰凭据。
 *
 * ## 为什么是单例
 * Registry 的 `hydrate()` 会打 `ai_info` + 读配置；多个组件各建一份既浪费又会打架。
 * 所以这里是**模块级单例**：第一次 `useCurrentModel()` 时懒启动，之后共享。
 * 订阅在模块级挂一次、活到进程结束 —— 视图是全局唯一的一份投影，不需要按组件退订。
 *
 * ## 失败姿态
 * 任何 IO 失败都不抛给 UI：`hydrate()` 内部已把 core 不可达吞成空能力面，
 * 这里再兜一层 try/catch，失败即保持"未配置"（顶栏显示未配置，不影响对话）。
 */

import { readonly, ref, type Ref } from 'vue'

import { ensureHydrated, getSharedRegistry } from '@/ai/model/bridge'
import { createModelReadOnly, resolveCurrentModel, type CurrentModelView, type ModelReadOnly } from '@/ai/model/consumer'
import type { ModelRegistry } from '@/ai/model/registry'

/** 未启动 / 启动失败时的中性值。 */
function emptyView(): CurrentModelView {
  return {
    set: false,
    label: '未配置',
    detail: '尚未选择模型',
    badge: '',
    title: '当前模型来自 ModelRegistry canonical：尚未设置',
    source: 'none',
    stale: true,
    pendingSync: false,
    dangling: false,
    canonical: { provider: '', model: '', apiBase: '' },
  }
}

const currentModel: Ref<CurrentModelView> = ref<CurrentModelView>(emptyView())

/**
 * 验收句柄（**只读**）—— 与 `window.__pwModels`（模型管理页）/ `window.__pwWorkspace`
 * 同一做法。
 *
 * 存在的意义：让"模型管理页取数的那份 Registry"与"AI 侧栏取数的那份 Registry"
 * 能在**同一页里**被机器证明是 `===` 同一个对象，而不是"两边碰巧都写着 canonical"。
 * 只挂出既有单例与一个纯读投影，**不新增任何写口**（写仍只在 bridge / 模型管理页）。
 */
declare global {
  interface Window {
    __pwAiModel?: {
      registry: ModelRegistry
      canonical: () => { provider: string; model: string }
      label: () => string
    }
  }
}

let registry: ModelRegistry | null = null
let reader: ModelReadOnly | null = null
let started = false

function publish(): void {
  if (!registry) return
  currentModel.value = resolveCurrentModel(registry)
}

/** 懒启动：取**共享** Registry → 挂只读投影 → 订阅 → hydrate（异步，不阻塞）。 */
function ensureStarted(): void {
  if (started) return
  started = true
  try {
    // TECH-04 §一：不再自己 new Registry —— 必须与 `stores/ai.ts`（AI 请求依据）
    // 共用同一个实例，否则"顶栏显示"与"实际调用"又会退化成两个来源。
    registry = getSharedRegistry()
    reader = createModelReadOnly(registry)
    reader.subscribe(() => publish())
    if (typeof window !== 'undefined') {
      // 与 AI 侧栏显示同一份投影；供验收脚本做对象同一性证明（见上方说明）。
      window.__pwAiModel = {
        registry,
        canonical: () => currentModel.value.canonical,
        label: () => currentModel.value.label,
      }
    }
  } catch {
    // 端口构造不该失败；真失败就保持"未配置"，不把异常甩给界面
    started = false
    registry = null
    reader = null
    return
  }
  // 先发布一次本地即可知的投影（此时 canonical 可能还是空），hydrate 到达后再发布一次
  publish()
  void ensureHydrated()
    .then(() => publish())
    .catch(() => publish())
}

export interface UseCurrentModel {
  /** 响应式"当前模型"读模型（只读 ref，外部改不了）。 */
  currentModel: Readonly<Ref<CurrentModelView>>
  /** 手动刷新（例如窗口重新聚焦时）。 */
  refresh: () => Promise<void>
  /** 只读门面（列表/Provider 查询用；**无写方法**）。 */
  reader: () => ModelReadOnly | null
}

/**
 * 取当前模型（只读）。
 *
 * ```vue
 * const { currentModel } = useCurrentModel()
 * // 模板：{{ currentModel.label }}
 * ```
 */
export function useCurrentModel(): UseCurrentModel {
  ensureStarted()
  return {
    currentModel: readonly(currentModel) as Readonly<Ref<CurrentModelView>>,
    refresh: async () => {
      if (!registry) return
      try {
        await registry.refreshCanonical()
      } catch {
        /* 刷新失败保留旧值 */
      }
      publish()
    },
    reader: () => reader,
  }
}

/** 测试/验收用：把模块级单例重置（不触达任何 IO）。 */
export function __resetCurrentModelForTest(): void {
  registry = null
  reader = null
  started = false
  currentModel.value = emptyView()
}
