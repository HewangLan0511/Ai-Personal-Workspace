/**
 * 个人档案状态（阶段7）。
 *
 * 设计：
 * - 一次 `overview()` 拉全（基础信息/技能/项目/时间线/建议），档案页单屏消费；
 * - 档案变化靠事件（`PROFILE_UPDATED` → `pw://event`）刷新，不轮询；
 *   确认建议可能发生在任何页面（学习页 / 项目页 / 档案页），统一以 core 为准。
 */

import { defineStore } from 'pinia'

import { on } from '@/api/eventBridge'
import {
  profileApi,
  type BasicInput,
  type ProfileOverview,
  type SuggestionKind,
} from '@/api/profileService'
import { logger } from '@/utils/logger'

let bound = false

interface ProfileState {
  data: ProfileOverview | null
  loading: boolean
  loaded: boolean
  error: string
}

export const useProfileStore = defineStore('profile', {
  state: (): ProfileState => ({
    data: null,
    loading: false,
    loaded: false,
    error: '',
  }),

  getters: {
    pendingCount(state): number {
      return state.data?.pendingCount ?? 0
    },
    basic(state) {
      return (
        state.data?.basic ?? { name: '', direction: '', interests: [], motto: '', updatedAt: '' }
      )
    },
  },

  actions: {
    async init(): Promise<void> {
      this.bindEvents()
      await this.reload()
    },

    async reload(): Promise<void> {
      this.loading = true
      try {
        this.data = await profileApi.overview()
        this.error = ''
      } catch (e) {
        this.error = '无法读取档案（核心服务可能仍在启动）'
        logger.warn('profile', `加载档案失败：${String(e)}`)
      } finally {
        this.loading = false
        this.loaded = true
      }
    },

    bindEvents(): void {
      if (bound) return
      bound = true
      on('PROFILE_UPDATED', () => {
        // 建议确认 / 手动编辑可能发生在任何页面，统一以 core 为准刷新
        void this.reload()
      })
    },

    // ---- 写操作（**用户动作**）-----------------------------------------

    async saveBasic(input: BasicInput): Promise<void> {
      await profileApi.basicSave(input)
      await this.reload()
    },

    /** 确认建议（逐条或批量）。返回确认条数。 */
    async confirmSuggestions(ids: number[]): Promise<number> {
      const n = await profileApi.confirm(ids)
      await this.reload()
      return n
    },

    async ignoreSuggestions(ids: number[]): Promise<number> {
      const n = await profileApi.ignore(ids)
      await this.reload()
      return n
    },

    async rejectKind(kind: SuggestionKind): Promise<void> {
      await profileApi.rejectKind(kind)
      await this.reload()
    },

    /** 扫描式采集（高频软件 → 技能建议）。返回新增条数。 */
    async scan(): Promise<number> {
      const n = await profileApi.scan()
      if (n > 0) await this.reload()
      return n
    },
  },
})
