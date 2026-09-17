/**
 * 学习成长 + 项目管理 API 封装（阶段6 · `09-阶段指令-学习成长.md`）。
 *
 * 通道：Tauri invoke 为主，HTTP `/api/v1/*` 为备用（curl / 脚本 / 验收）。
 * 两侧**逻辑同源**（core 里都调 `LearningRepo` / `learning::apply_*`）。
 *
 * ⚠️ 红线 V3 在客户端的体现：本文件里**没有**任何"把 AI 建议直接写库"的函数。
 * `suggest()` 只返回建议（`advisory: true`）；要落库必须显式调用
 * `roadmapConfirm()` / `nodeEdit()` —— 那是**用户动作**的入口。
 */

import { inTauri, invokeCore, request } from './client'

export type GoalStatus = 'not_started' | 'learning' | 'paused' | 'done' | 'archived'
export type NodeStatus = 'not_started' | 'learning' | 'done' | 'paused'
export type Priority = 'low' | 'medium' | 'high'
/** `roadmap` = 生成路线（严格 JSON）；另外两个是自然语言建议 */
export type SuggestKind = 'roadmap' | 'optimize' | 'summary'

export interface Progress {
  done: number
  total: number
  percent: number
}

export interface LearningGoal {
  id: number
  title: string
  description: string | null
  status: GoalStatus
  expectedAt: string | null
  priority: Priority
  /** AI 原始输出快照（仅"采纳过的版本"，用于重新生成时对比） */
  roadmapRaw: string | null
  lastRemindedAt: string | null
  createdAt: string
  updatedAt: string
  progress: Progress
}

export interface GoalInput {
  title: string
  description?: string | null
  expectedAt?: string | null
  priority?: Priority
}

export interface GoalPatch {
  title?: string
  description?: string | null
  expectedAt?: string | null
  priority?: Priority
  status?: GoalStatus
}

export interface RoadmapNode {
  id: number
  goalId: number
  title: string
  status: NodeStatus
  note: string | null
  estimated: string | null
  resources: string[]
  sortOrder: number
  completedAt: string | null
  createdAt: string
  updatedAt: string
}

/** 建议态节点（**未落库**）：AI 产出或用户手编的草稿 */
export interface NodeDraft {
  title: string
  status?: NodeStatus
  note?: string | null
  estimated?: string | null
  resources?: string[]
}

export interface NodePatch {
  title?: string
  status?: NodeStatus
  note?: string | null
  estimated?: string | null
  resources?: string[]
  sortOrder?: number
}

export interface LearningUpdate {
  id: number
  goalId: number
  nodeId: number | null
  content: string
  createdAt: string
}

/** AI 建议的返回（**只读结果**，不代表任何数据已变更） */
export interface SuggestResult {
  kind: SuggestKind
  /** ★ 恒为 true：UI 必须据此展示「AI 建议，待确认」 */
  advisory: boolean
  promptKey: string
  raw: string
  /** true = 没解析出结构，请走文本展示 + 手动录入 */
  degraded: boolean
  reason: string | null
  nodes: NodeDraft[]
  chunkCount: number
  durationMs: number
}

export type ProjectStatus = 'ongoing' | 'paused' | 'done'

export interface Project {
  id: number
  name: string
  role: string | null
  summary: string | null
  techStack: string[]
  startDate: string | null
  endDate: string | null
  status: ProjectStatus
  directory: string | null
  modeName: string | null
  goalId: number | null
  goalTitle: string | null
  createdAt: string
  updatedAt: string
  /** 仅写入返回：项目刚完成且挂着目标时=true，UI 可提议"是否一并完成目标" */
  linkedGoalDone?: boolean
}

export interface ProjectInput {
  name: string
  role?: string | null
  summary?: string | null
  techStack?: string[]
  startDate?: string | null
  endDate?: string | null
  status?: ProjectStatus
  directory?: string | null
  modeName?: string | null
  goalId?: number | null
}

/** 编辑入参：关联字段 `null` 表示**解除绑定**，`undefined` 表示不动 */
export interface ProjectPatch {
  name?: string
  role?: string | null
  summary?: string | null
  techStack?: string[]
  startDate?: string | null
  endDate?: string | null
  status?: ProjectStatus
  directory?: string | null
  modeName?: string | null
  goalId?: number | null
}

export interface ReminderHit {
  goalId: number
  title: string
  idleDays: number
}

// ---------------------------------------------------------------- 学习目标

export async function goals(): Promise<LearningGoal[]> {
  if (inTauri()) return invokeCore<LearningGoal[]>('learning_goals_list')
  return request<LearningGoal[]>('/api/v1/learning/goals')
}

export async function goalAdd(input: GoalInput): Promise<LearningGoal> {
  if (inTauri()) return invokeCore<LearningGoal>('learning_goal_add', { input })
  return request<LearningGoal>('/api/v1/learning/goals', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function goalUpdate(id: number, patch: GoalPatch): Promise<LearningGoal> {
  if (inTauri()) return invokeCore<LearningGoal>('learning_goal_update', { id, patch })
  return request<LearningGoal>(`/api/v1/learning/goals/${id}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function goalRemove(id: number): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('learning_goal_delete', { id })
    return
  }
  await request<unknown>(`/api/v1/learning/goals/${id}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------- 路线节点

export async function nodes(goalId: number): Promise<RoadmapNode[]> {
  if (inTauri()) return invokeCore<RoadmapNode[]>('learning_nodes_list', { goalId })
  return request<RoadmapNode[]>(`/api/v1/learning/goals/${goalId}/nodes`)
}

/**
 * 确认采纳一条路线（**用户动作**）。
 *
 * `replace=false` 且该目标已有节点时 core 会拒绝 —— 覆盖会重置已标记的进度，
 * 属破坏性操作，必须在 UI 上二次确认后才传 `true`。
 */
export async function roadmapConfirm(
  goalId: number,
  list: NodeDraft[],
  replace = false,
  raw?: string,
): Promise<RoadmapNode[]> {
  if (inTauri()) {
    return invokeCore<RoadmapNode[]>('learning_roadmap_confirm', {
      goalId,
      nodes: list,
      replace,
      raw: raw ?? null,
    })
  }
  return request<RoadmapNode[]>(`/api/v1/learning/goals/${goalId}/roadmap`, {
    method: 'POST',
    body: JSON.stringify({ nodes: list, replace, raw }),
  })
}

export async function nodeAdd(goalId: number, input: NodeDraft): Promise<RoadmapNode> {
  if (inTauri()) return invokeCore<RoadmapNode>('learning_node_add', { goalId, input })
  return request<RoadmapNode>('/api/v1/learning/nodes', {
    method: 'POST',
    body: JSON.stringify({ goalId, input }),
  })
}

export async function nodeEdit(id: number, patch: NodePatch): Promise<RoadmapNode> {
  if (inTauri()) return invokeCore<RoadmapNode>('learning_node_update', { id, patch })
  return request<RoadmapNode>(`/api/v1/learning/nodes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function nodeRemove(id: number): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('learning_node_delete', { id })
    return
  }
  await request<unknown>(`/api/v1/learning/nodes/${id}`, { method: 'DELETE' })
}

export async function nodeMove(id: number, delta: number): Promise<RoadmapNode[]> {
  if (inTauri()) return invokeCore<RoadmapNode[]>('learning_node_move', { id, delta })
  return request<RoadmapNode[]>(`/api/v1/learning/nodes/${id}/move`, {
    method: 'POST',
    body: JSON.stringify({ delta }),
  })
}

// ---------------------------------------------------------------- 更新记录

export async function updates(goalId: number, limit = 50): Promise<LearningUpdate[]> {
  if (inTauri()) return invokeCore<LearningUpdate[]>('learning_updates_list', { goalId, limit })
  return request<LearningUpdate[]>(`/api/v1/learning/goals/${goalId}/updates?limit=${limit}`)
}

export async function updateAdd(
  goalId: number,
  nodeId: number | null,
  content: string,
): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('learning_update_add', { goalId, nodeId, content })
    return
  }
  await request<unknown>('/api/v1/learning/updates', {
    method: 'POST',
    body: JSON.stringify({ goalId, nodeId, content }),
  })
}

// ---------------------------------------------------------------- AI（只建议）

/**
 * 让 AI 产出建议。**不写任何学习数据**（红线 V3）—— 结果只用于展示。
 *
 * 需要用户在 AI 侧栏里选过 Provider（复用同一套凭据与 Provider 抽象）。
 */
export async function suggest(args: {
  goalId?: number | null
  kind: SuggestKind
  provider: string
  model?: string
  apiBase?: string
  extra?: string
}): Promise<SuggestResult> {
  const payload = {
    goalId: args.goalId ?? null,
    kind: args.kind,
    provider: args.provider,
    model: args.model ?? '',
    apiBase: args.apiBase ?? '',
    extra: args.extra ?? '',
  }
  if (inTauri()) return invokeCore<SuggestResult>('learning_ai_suggest', payload)
  return request<SuggestResult>('/api/v1/learning/suggest', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 立即跑一次提醒扫描（改完阈值后不必等后台轮询）。 */
export async function checkReminders(): Promise<ReminderHit[]> {
  if (inTauri()) return invokeCore<ReminderHit[]>('learning_check_reminders')
  return request<ReminderHit[]>('/api/v1/learning/reminders/check', { method: 'POST' })
}

// ---------------------------------------------------------------- 项目管理

export async function projects(status?: string, modeName?: string): Promise<Project[]> {
  if (inTauri()) {
    return invokeCore<Project[]>('projects_list', {
      status: status ?? null,
      modeName: modeName ?? null,
    })
  }
  const q = new URLSearchParams()
  if (status) q.set('status', status)
  if (modeName) q.set('modeName', modeName)
  return request<Project[]>(`/api/v1/projects${q.toString() ? `?${q}` : ''}`)
}

export async function projectAdd(input: ProjectInput): Promise<Project> {
  if (inTauri()) return invokeCore<Project>('project_add', { input })
  return request<Project>('/api/v1/projects', { method: 'POST', body: JSON.stringify(input) })
}

export async function projectUpdate(id: number, patch: ProjectPatch): Promise<Project> {
  if (inTauri()) return invokeCore<Project>('project_update', { id, patch })
  return request<Project>(`/api/v1/projects/${id}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function projectRemove(id: number): Promise<void> {
  if (inTauri()) {
    await invokeCore<unknown>('project_delete', { id })
    return
  }
  await request<unknown>(`/api/v1/projects/${id}`, { method: 'DELETE' })
}

/** 某模式绑定的项目（09 §6 联动：进入模式时显示当前项目）。 */
export async function projectByMode(modeName: string): Promise<Project | null> {
  if (inTauri()) return invokeCore<Project | null>('project_by_mode', { modeName })
  return request<Project | null>(
    `/api/v1/project/by-mode?modeName=${encodeURIComponent(modeName)}`,
  )
}

export const learningApi = {
  goals,
  goalAdd,
  goalUpdate,
  goalRemove,
  nodes,
  roadmapConfirm,
  nodeAdd,
  nodeEdit,
  nodeRemove,
  nodeMove,
  updates,
  updateAdd,
  suggest,
  checkReminders,
}

export const projectApi = {
  list: projects,
  add: projectAdd,
  update: projectUpdate,
  remove: projectRemove,
  byMode: projectByMode,
}

/** 状态展示元数据（UI 与验收脚本共用一套口径，避免各写各的颜色/文案）。 */
export const GOAL_STATUS_META: Record<GoalStatus, { label: string; color: string }> = {
  not_started: { label: '未开始', color: 'gray' },
  learning: { label: '学习中', color: 'blue' },
  done: { label: '已完成', color: 'green' },
  paused: { label: '暂停', color: 'yellow' },
  archived: { label: '已归档', color: 'gray' },
}

export const NODE_STATUS_META: Record<NodeStatus, { label: string; color: string }> = {
  not_started: { label: '未开始', color: 'gray' },
  learning: { label: '学习中', color: 'blue' },
  done: { label: '完成', color: 'green' },
  paused: { label: '暂停', color: 'yellow' },
}
