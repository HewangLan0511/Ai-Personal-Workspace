/**
 * 插件组件侧挂区（设计稿 `WIDGETS` + `widgetColHtml()`）
 * ====================================================
 *
 * 唯一来源 = `personal-workspace-ui/index.html`：
 * ```js
 * const WIDGETS = [
 *   {id:'weather', name:'天气',   icon:'cloud',   tint:2, on:true},
 *   {id:'todo',    name:'待办',   icon:'check-c', tint:3, on:true},
 *   {id:'music',   name:'正在播放', icon:'music',   tint:4, on:true},
 *   {id:'clip',    name:'剪贴板', icon:'copy',     tint:5, on:false},
 *   {id:'clock',   name:'专注',   icon:'clock',    tint:1, on:false},
 * ];
 * ```
 *
 * ★ 这份清单**不是**首页 Widget 网格（`stores/widgets.ts`）。
 *   两者是两个不同的东西，刻意不合并：
 *     - `stores/widgets.ts` → 内容区（`.page`）里的卡片网格，有 size/priority/使用频次；
 *     - 本文件 → 内容区与 AI 侧栏**之间**那条 224px 侧挂列，只有顺序与开关，
 *       没有尺寸概念（设计稿里每个 `.wcard` 都是 `flex:0 0 auto` 等高的）。
 *   把两者合成一份会立刻产生"同一个 id 两套字段"的伪契约。
 *
 * ★ 持久化：`ui.shell.widgets`（`array`，本轮新登记于 `core/src/db/config.rs`）。
 *   与 `stores/widgets.ts` 同样的**串行写**纪律 —— `put` 可能走 invoke 也可能走
 *   HTTP 降级，完成顺序不保证；不串行就会出现"后发先至"用旧快照覆盖新快照。
 */

import { defineStore } from 'pinia'

import { configApi } from '@/api/configService'

const KEY = 'ui.shell.widgets'

export interface SideWidget {
  id: string
  name: string
  /** 设计稿图标名（`components/PwIcon.vue` 的 key） */
  icon: string
  /** 设计稿 tint 序（1..6，对应 `.tint*` 底色族） */
  tint: number
  /** 是否出现在侧挂列里（设计稿 `on`） */
  on: boolean
}

/** 设计稿 WIDGETS 逐条（顺序即设计稿顺序） */
export const DEFAULT_SIDE_WIDGETS: SideWidget[] = [
  { id: 'weather', name: '天气', icon: 'cloud', tint: 2, on: true },
  { id: 'todo', name: '待办', icon: 'check-c', tint: 3, on: true },
  { id: 'music', name: '正在播放', icon: 'music', tint: 4, on: true },
  { id: 'clip', name: '剪贴板', icon: 'copy', tint: 5, on: false },
  { id: 'clock', name: '专注', icon: 'clock', tint: 1, on: false },
]

let writeQueue: Promise<void> = Promise.resolve()
function enqueueWrite(task: () => Promise<void>): Promise<void> {
  writeQueue = writeQueue.then(task, task)
  return writeQueue
}

/**
 * 合并落库快照与设计稿默认值。
 *
 * 为什么要合并而不是直接用快照：设计稿后续若新增一个挂件，老用户的快照里没有它。
 * 直接覆盖会让新挂件**永远不出现**（而它本可以是默认开着的）。合并口径：
 *   - 快照里有、设计稿也有的 → 用快照（尊重用户顺序与开关）；
 *   - 快照里没有、设计稿有的 → 追加到末尾，用设计稿默认；
 *   - 快照里有、设计稿已经没有的 → **丢弃**（设计稿删掉的东西不该继续挂在 UI 上）。
 */
function merge(saved: SideWidget[] | null): SideWidget[] {
  if (!saved || !Array.isArray(saved) || saved.length === 0) {
    return DEFAULT_SIDE_WIDGETS.map((w) => ({ ...w }))
  }
  const known = new Map(DEFAULT_SIDE_WIDGETS.map((w) => [w.id, w]))
  const out: SideWidget[] = []
  for (const item of saved) {
    if (!item || typeof item.id !== 'string') continue
    const base = known.get(item.id)
    if (!base) continue
    out.push({
      id: base.id,
      name: base.name,
      icon: base.icon,
      tint: base.tint,
      on: item.on === true,
    })
  }
  for (const w of DEFAULT_SIDE_WIDGETS) {
    if (!out.some((x) => x.id === w.id)) out.push({ ...w })
  }
  return out
}

export const useWidgetColStore = defineStore('widgetCol', {
  state: () => ({
    /** 全量清单（含已关闭项），顺序 = 用户在侧挂列里看到的顺序 */
    items: DEFAULT_SIDE_WIDGETS.map((w) => ({ ...w })) as SideWidget[],
    /** 侧挂列是否整体收起（设计稿 `state.widgetCol`；收起后仍占位并露出「+ 添加组件」） */
    collapsed: false,
    loaded: false,
  }),
  getters: {
    /** 侧挂列里真正要渲染的（设计稿 `WIDGETS.filter(w=>w.on)`） */
    visible(state): SideWidget[] {
      return state.items.filter((w) => w.on)
    },
  },
  actions: {
    async load() {
      if (this.loaded) return
      const saved = await configApi.get<SideWidget[] | null>(KEY, null)
      this.items = merge(saved)
      this.loaded = true
    },
    async persist() {
      await enqueueWrite(() => configApi.put(KEY, this.items))
    },
    /**
     * 拖拽排序落位 —— 逐值移植设计稿 `widgetSortCb(f,t)`：
     * ```js
     * const on = WIDGETS.filter(w=>w.on);
     * moveItem(on, f, t);
     * let k = 0; for(let i=0;i<WIDGETS.length;i++) if(WIDGETS[i].on) WIDGETS[i] = on[k++];
     * ```
     * ★ `f` / `t` 是**可见项**里的下标，不是全量清单里的下标。
     *   只重排"开着的那几个"，再按原槽位写回 —— 关着的挂件保持它在全量清单里的
     *   位置不动（否则用户把 A 从第 1 拖到第 2，关着的 D 会莫名挤到中间）。
     */
    async reorderVisible(f: number, t: number) {
      const on = this.items.filter((w) => w.on)
      if (f === t || f < 0 || t < 0 || f >= on.length || t >= on.length) return
      const [item] = on.splice(f, 1)
      on.splice(t, 0, item)
      let k = 0
      for (let i = 0; i < this.items.length; i++) {
        if (this.items[i].on) this.items[i] = on[k++]
      }
      await this.persist()
    },
    /** 开关某个挂件（设计稿「自定义」面板里的勾选） */
    async toggle(id: string) {
      const w = this.items.find((x) => x.id === id)
      if (!w) return
      w.on = !w.on
      await this.persist()
    },
  },
})
