/**
 * 学习成长状态（阶段6）。
 *
 * 关键设计：
 * - **提醒靠事件**（`LEARNING_REMINDER` 经事件桥 → `pw://event`），不轮询；
 *   启动时还会从事件桥的"最近事件"环形缓冲里**补捞**一次 —— 否则后台调度器
 *   在页面订阅之前发出的提醒会永远看不到（首启 3 秒后就扫描，那时用户还没点进页面）。
 * - **进度用 core 算好的值**（`goal.progress`），前端不自己数节点 ——
 *   两侧各算一套迟早会不一致。
 */

import { defineStore } from 'pinia'

import { on, recentEvents } from '@/api/eventBridge'
import {
  learningApi,
  type GoalPatch,
  type LearningGoal,
  type ReminderHit,
} from '@/api/learningService'
import { logger } from '@/utils/logger'

/** 事件桥是单例：多个 store 各自 init 时不能重复绑定（否则提醒会重复追加）。 */
let bound = false

interface LearningState {
  goals: LearningGoal[]
  /** 当前活跃的提醒（后台调度器推来的） */
  reminders: ReminderHit[]
  /** 用户点过"稍后"的提醒（仅本地隐藏，不写库 —— 冷却由 core 的 7 天窗口负责） */
  dismissed: number[]
  loading: boolean
  loaded: boolean
  error: string
}

export const useLearningStore = defineStore('learning', {
  state: (): LearningState => ({
    goals: [],
    reminders: [],
    dismissed: [],
    loading: false,
    loaded: false,
    error: '',
  }),

  getters: {
    /** 实际要展示的提醒（排除用户已"稍后"的） */
    activeReminders(state): ReminderHit[] {
      return state.reminders.filter((r) => !state.dismissed.includes(r.goalId))
    },
    byId(state): (id: number) => LearningGoal | undefined {
      return (id: number) => state.goals.find((g) => g.id === id)
    },
  },

  actions: {
    async init(): Promise<void> {
      if (this.loaded) return
      this.loaded = true
      this.bindEvents()
      this.collectRecent()
      await this.reload()
    },

    async reload(): Promise<void> {
      this.loading = true
      try {
        this.goals = await learningApi.goals()
        this.error = ''
      } catch (e) {
        this.error = '无法读取学习目标（核心服务可能仍在启动）'
        logger.warn('learning', `加载学习目标失败：${String(e)}`)
      } finally {
        this.loading = false
      }
    },

    bindEvents(): void {
      if (bound) return
      bound = true
      on('LEARNING_REMINDER', (env) => {
        const p = env.payload as unknown as ReminderHit
        if (!p?.goalId) return
        if (this.reminders.some((r) => r.goalId === p.goalId)) return
        this.reminders.push(p)
      })
      on('LEARNING_PROGRESS_UPDATED', () => {
        // 状态可能在别处（提醒条 / 项目页）被改，统一以 core 为准刷新
        void this.reload()
      })
    },

    /**
     * 补捞事件桥缓冲里的历史提醒。
     *
     * `recentEvents()` 是事件桥自带的环形缓冲（容量 200）—— 页面订阅晚于事件发生
     * 是**常态**（后台 3 秒后就扫描），不补捞的话用户永远看不到首轮提醒。
     */
    collectRecent(): void {
      for (const env of recentEvents()) {
        if (env.event !== 'LEARNING_REMINDER') continue
        const p = env.payload as unknown as ReminderHit
        if (!p?.goalId) continue
        if (this.reminders.some((r) => r.goalId === p.goalId)) continue
        this.reminders.push(p)
      }
    },

    dismiss(goalId: number): void {
      if (!this.dismissed.includes(goalId)) this.dismissed.push(goalId)
    },

    /** 处理提醒的三个动作：继续 / 暂停 / 归档（09 §5）。 */
    async actOnReminder(goalId: number, status: 'learning' | 'paused' | 'archived'): Promise<void> {
      await this.updateGoal(goalId, { status })
      this.dismiss(goalId)
    },

    // ---- 写操作（**用户动作**）-----------------------------------------

    async addGoal(input: {
      title: string
      description?: string | null
      expectedAt?: string | null
      priority?: 'low' | 'medium' | 'high'
    }): Promise<LearningGoal> {
      const g = await learningApi.goalAdd(input)
      await this.reload()
      return g
    },

    async updateGoal(id: number, patch: GoalPatch): Promise<LearningGoal> {
      const g = await learningApi.goalUpdate(id, patch)
      await this.reload()
      return g
    },

    async removeGoal(id: number): Promise<void> {
      await learningApi.goalRemove(id)
      await this.reload()
    },

    /** 手动跑一次提醒扫描（改完阈值后立即可见效果）。 */
    async checkReminders(): Promise<ReminderHit[]> {
      const hits = await learningApi.checkReminders()
      for (const h of hits) {
        if (!this.reminders.some((r) => r.goalId === h.goalId)) this.reminders.push(h)
      }
      return hits
    },
  },
})
