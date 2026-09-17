/**
 * 软件库状态（阶段2 / 05 §5 UI 页面）。
 *
 * 约定：**过滤与排序由 core 负责**（`AppsRepo::list`），store 只持有结果，
 * 不在前端重复实现一遍排序 —— 否则两端顺序会漂移。
 */

import { defineStore } from 'pinia'

import {
  appsApi,
  NativeOnlyError,
  type AppInput,
  type AppItem,
  type AppPatch,
  type InstalledApp,
  type LaunchResult,
} from '@/api/appsService'

export type AppsViewMode = 'grid' | 'list'

export const useAppsStore = defineStore('apps', {
  state: () => ({
    items: [] as AppItem[],
    categories: [] as string[],
    /** `appId → pid`，由 `apps_running` 同步（05 §3） */
    running: {} as Record<string, number>,
    loading: false,
    error: '',
    /** 上一次启动的结果（供 UI 提示"已在运行"等） */
    lastLaunch: null as LaunchResult | null,

    // ---- 视图状态 ----
    view: 'grid' as AppsViewMode,
    category: '' as string, // 空字符串 = 全部
    search: '',
    /** 图标 data URL 缓存：`iconPath → dataURL`（避免每次渲染都读盘） */
    iconCache: {} as Record<string, string>,
  }),

  getters: {
    /** 某软件是否正在运行（05 §2/§3 的"运行中"标记）。 */
    isRunning: (state) => (id: number) => state.running[String(id)] !== undefined,
    runningCount: (state) => Object.keys(state.running).length,
  },

  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        this.items = await appsApi.list(this.category || undefined, this.search || undefined)
        this.categories = await appsApi.categories()
        this.running = await appsApi.running()
      } catch (err) {
        this.error = String(err)
      } finally {
        this.loading = false
      }
    },

    /** 仅刷新运行状态（供 5s 轮询调用，不重拉列表）。 */
    async refreshRunning() {
      try {
        this.running = await appsApi.running()
      } catch {
        /* 降级环境无可上报状态，忽略 */
      }
    },

    async setCategory(category: string) {
      this.category = category
      await this.load()
    },

    async setSearch(search: string) {
      this.search = search
      await this.load()
    },

    async add(input: AppInput): Promise<AppItem> {
      const item = await appsApi.add(input)
      await this.load()
      return item
    },

    async addMany(inputs: AppInput[]): Promise<number> {
      let n = 0
      for (const input of inputs) {
        try {
          await appsApi.add(input)
          n += 1
        } catch {
          // 单条失败（重复路径等）不阻塞整批 —— 05 §2「失败要可见但不中断」
        }
      }
      await this.load()
      return n
    },

    async update(id: number, patch: AppPatch) {
      await appsApi.update(id, patch)
      await this.load()
    },

    async remove(id: number) {
      await appsApi.remove(id)
      await this.load()
    },

    async launch(id: number): Promise<LaunchResult> {
      const res = await appsApi.launch(id)
      this.lastLaunch = res
      await this.refreshRunning()
      await this.load() // launch_count 变了，顺序会变（05 §4）
      return res
    },

    async togglePin(item: AppItem) {
      await this.update(item.id, { pinned: !item.pinned })
    },

    /** 选择文件 → 自动补全（05 §1）。返回补全后的入参，由调用方确认后入库。 */
    async pickAndProbe(): Promise<AppInput | null> {
      const path = await appsApi.pickFile()
      if (!path) return null
      let name = path.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') ?? path
      let icon: string | null = null
      try {
        const probed = await appsApi.probe(path)
        if (probed?.name) name = probed.name
        icon = probed?.iconPath ?? null
      } catch {
        // 自动补全是增强项，失败用文件名兜底（05 §1"从 FileDescription **或文件名**"）
      }
      return { name, path, args: '', icon, type: 'exe', category: null }
    },

    async scanInstalled(): Promise<InstalledApp[]> {
      return appsApi.scan()
    },

    /** 按需加载图标（data URL），带缓存。失败返回 null（前端走首字母占位）。 */
    async loadIcon(iconPath: string | null): Promise<string | null> {
      if (!iconPath) return null
      const cached = this.iconCache[iconPath]
      if (cached) return cached
      try {
        const url = await appsApi.iconData(iconPath)
        this.iconCache = { ...this.iconCache, [iconPath]: url }
        return url
      } catch {
        return null
      }
    },
  },
})

export { NativeOnlyError }
