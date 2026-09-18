import { defineStore } from 'pinia'

import type { Widget } from '@/api/types'
import { configApi } from '@/api/configService'

const KEY = 'ui.dashboard.widgets'
/** 使用次数：{ [widgetId]: number }，单独存键（REVIEW-003 C-01 / 04 §3） */
const KEY_USAGE = 'ui.dashboard.usage'
/** 用户是否手动调整过布局；与 widgets 分开持久化，避免"自动落库"被误判为手动锁定 */
const KEY_LOCK = 'ui.dashboard.layout_locked'

/** 默认 Widget 清单（04 §3 V1 必备）——priority 越大越靠前、展示越大 */
const DEFAULTS: Widget[] = [
  { id: 'work-mode', name: '工作模式', size: 'large', position: { row: 0, col: 0 }, priority: 100, enabled: true },
  { id: 'current-project', name: '当前项目', size: 'medium', position: { row: 0, col: 2 }, priority: 90, enabled: true },
  { id: 'ai-quick', name: 'AI 助手', size: 'medium', position: { row: 1, col: 2 }, priority: 80, enabled: true },
  { id: 'frequent-apps', name: '常用软件', size: 'large', position: { row: 2, col: 0 }, priority: 70, enabled: true },
  { id: 'learning-progress', name: '学习路线', size: 'small', position: { row: 2, col: 2 }, priority: 50, enabled: true },
  { id: 'weather', name: '天气', size: 'small', position: { row: 2, col: 3 }, priority: 30, enabled: true },
  { id: 'device-status', name: '设备状态', size: 'small', position: { row: 3, col: 3 }, priority: 20, enabled: true },
]

type WidgetSize = Widget['size']

/**
 * 配置写入串行化。
 *
 * 为什么需要：`recordUse` 每点一次都会各发一次 `put`，而 `put` 内部可能走 invoke
 * 也可能走 HTTP 降级，**完成顺序不保证** —— 后发的写有可能先落，于是旧快照覆盖新快照。
 * 这不是理论担忧：CDP 探针实测观察到落库值演变 `{"weather":2} → {"weather":6} → {"weather":10}`
 * （本应直接是 10），收敛靠的是"最后一次恰好最后到"，而非机制保证。
 * 串行化后按发起顺序落，**最后发起的写必然是最终值**。
 */
let writeQueue: Promise<void> = Promise.resolve()

function enqueueWrite(task: () => Promise<void>): Promise<void> {
  writeQueue = writeQueue.then(task, task)
  return writeQueue
}

/**
 * 尺寸判定（04 §3「高频大、低频小」+「priority 高 → 展示大」双规则合一）：
 * - usage ≥ 10 → large；≥ 3 → medium；
 * - 数据不足时以 priority 为**下限**参考（priority ≥ 90 至少 medium），避免
 *   刚点一下就把它依赖的「工作模式」缩成小卡。
 */
export function sizeFor(useCount: number, priority: number): WidgetSize {
  if (useCount >= 10) return 'large'
  if (useCount >= 3) return 'medium'
  return priority >= 90 ? 'medium' : 'small'
}

export const useWidgetStore = defineStore('widgets', {
  state: () => ({
    widgets: [] as Widget[],
    usage: {} as Record<string, number>,
    /** 用户手动调整过顺序后，不再按 priority 自动覆盖（04 §3 layout_locked） */
    layoutLocked: false,
    loaded: false,
  }),
  getters: {
    /** 展示顺序：锁定用手动顺序，未锁定按 priority 降序 */
    ordered(state): Widget[] {
      const list = state.widgets.filter((w) => w.enabled)
      if (state.layoutLocked) return list
      return [...list].sort((a, b) => b.priority - a.priority)
    },
    /** 全部组件（含已停用），供「组件管理」面板使用 */
    all(state): Widget[] {
      return state.widgets
    },
  },
  actions: {
    async load() {
      if (this.loaded) return
      const [saved, savedUsage, savedLock] = await Promise.all([
        configApi.get<Widget[] | null>(KEY, null),
        configApi.get<Record<string, number>>(KEY_USAGE, {}),
        configApi.get<boolean>(KEY_LOCK, false),
      ])
      const hasSaved = saved !== null && Array.isArray(saved) && saved.length > 0
      this.widgets = hasSaved ? (saved as Widget[]) : DEFAULTS.map((w) => ({ ...w }))
      this.usage = savedUsage ?? {}
      // 只有用户**真的手动调过**才算锁定；恢复默认时重置。
      this.layoutLocked = hasSaved ? savedLock === true : false
      this.loaded = true
    },
    async persist() {
      await enqueueWrite(() => configApi.put(KEY, this.widgets))
    },
    async persistLock() {
      await enqueueWrite(() => configApi.put(KEY_LOCK, this.layoutLocked))
    },
    async persistUsage() {
      await enqueueWrite(() => configApi.put(KEY_USAGE, this.usage))
    },
    /** 记录一次使用（04 §3「记录每个 Widget 的点击/使用次数 → 存 config 表」） */
    async recordUse(id: string) {
      if (!this.widgets.some((w) => w.id === id)) return
      const count = (this.usage[id] ?? 0) + 1
      this.usage = { ...this.usage, [id]: count }
      const resized = this.autoSize(id, count)
      if (resized) await this.persist()
      await this.persistUsage()
    },
    async moveUp(id: string) {
      const idx = this.widgets.findIndex((w) => w.id === id)
      if (idx <= 0) return
      const [item] = this.widgets.splice(idx, 1)
      this.widgets.splice(idx - 1, 0, item)
      this.layoutLocked = true
      await this.persist()
      await this.persistLock()
    },
    async moveDown(id: string) {
      const idx = this.widgets.findIndex((w) => w.id === id)
      if (idx < 0 || idx >= this.widgets.length - 1) return
      const [item] = this.widgets.splice(idx, 1)
      this.widgets.splice(idx + 1, 0, item)
      this.layoutLocked = true
      await this.persist()
      await this.persistLock()
    },
    /** 停用/启用组件（04 §3 enabled 字段；REVIEW-003 L-016 补 UI 入口） */
    async toggleEnabled(id: string) {
      const w = this.widgets.find((item) => item.id === id)
      if (!w) return
      w.enabled = !w.enabled
      await this.persist()
    },
    /**
     * 拖拽排序（设计稿 `openCustomize` → `enableSort('#arrangeWidgets', '.arrange-row', …)`）。
     *
     * 语义 = `moveItem(list, from, to)`：**先摘后插**（`from` 是拖动前下标，
     * `to` 是拖动落点下标）—— 与 `useListSort` 的 `move` 模式回调口径一致。
     *
     * 与设计稿的**有意差异**：设计稿只重排 `enabled` 子序列再回填（`WIDGETS.filter(w=>w.on)`
     * + 回填循环），但传进回调的 `from/to` 是**含停用项的全量下标** ——
     * 两个下标空间不一致，只要有任意一个组件被关掉就会移错位。本工程改为
     * **直接重排全量数组**：编排列表把停用项也画出来了（`.arrange-row.off`），
     * 所以"看到的顺序"与"存的顺序"是同一个数组，下标天然自洽。
     *
     * 与 `moveUp/moveDown` 一样，手动排序 → 顺手锁定布局（04 §3 `layout_locked`），
     * 否则下一次 `autoSize` 会按 priority 把顺序又冲掉。
     */
    async reorderWidget(from: number, to: number) {
      const n = this.widgets.length
      if (from === to || from < 0 || to < 0 || from >= n || to >= n) return
      const [item] = this.widgets.splice(from, 1)
      this.widgets.splice(to, 0, item)
      this.layoutLocked = true
      await this.persist()
      await this.persistLock()
    },
    /**
     * 固定布局：不再按使用频率自动覆盖尺寸与顺序（04 §3 `layout_locked`）。
     *
     * 与 `moveUp/moveDown` 的区别：那两个是"手动拖了一次 → 顺手锁定"的副作用入口，
     * 本动作是**显式选择**（设置页「外观 · 首页布局 = 固定」）。两种情况观感一样
     * （都不再自动变），但语义不能混：用户点了"固定"不该被记成"他拖过卡片"。
     * 只写锁定键，不重排尺寸 —— 固定 = 保持现状。
     */
    async lockLayout() {
      if (this.layoutLocked) return
      this.layoutLocked = true
      await this.persistLock()
    },
    /** 解除锁定，恢复「按 frequency + priority 自动布局」（04 §3 的出口，避免锁死） */
    async unlockLayout() {
      this.layoutLocked = false
      for (const w of this.widgets) {
        w.size = sizeFor(this.usage[w.id] ?? 0, w.priority)
      }
      await this.persist()
      await this.persistLock()
    },
    /** 未锁定时按使用频率自动调整尺寸；返回是否真的发生尺寸变化 */
    autoSize(id: string, useCount: number): boolean {
      if (this.layoutLocked) return false
      const w = this.widgets.find((item) => item.id === id)
      if (!w) return false
      const next = sizeFor(useCount, w.priority)
      if (w.size === next) return false
      w.size = next
      return true
    },
  },
})
