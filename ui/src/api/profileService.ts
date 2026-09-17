/**
 * 个人数字档案 API 封装（阶段7 · `10-阶段指令-个人档案.md`）。
 *
 * 通道：Tauri invoke 为主，HTTP `/api/v1/profile/*` 为备用（curl / 脚本 / 验收）。
 *
 * ⚠️ 红线在客户端的体现：本文件里 `suggestionsConfirm()` 是**建议 → 档案的唯一入口**，
 * 只应绑定在"用户点确认"的事件上；没有任何函数会把建议数据悄悄写进档案。
 */

import { inTauri, invokeCore, request } from './client'

export type SkillCategory = 'other' | 'lang' | 'framework' | 'tool' | 'domain'
export type SuggestionKind = 'timeline' | 'skill' | 'project'
export type SuggestionStatus = 'pending' | 'confirmed' | 'ignored'
export type TimelineType = 'learning' | 'project' | 'skill' | 'cert'

export interface ProfileBasic {
  name: string
  direction: string
  interests: string[]
  motto: string
  updatedAt: string
}

export interface BasicInput {
  name?: string
  direction?: string
  /** 不传 = 保持原值；传数组（可空）= 覆盖 */
  interests?: string[]
  motto?: string
}

export interface ProfileSkill {
  id: number
  name: string
  level: number
  category: SkillCategory
  source: 'user' | 'ai_suggested'
  confirmed: boolean
  updatedAt: string
}

export interface SkillInput {
  name: string
  level?: number
  category?: SkillCategory
}

export interface SkillPatch {
  name?: string
  level?: number
  category?: SkillCategory
}

export interface ProfileProjectEntry {
  id: number
  name: string
  role: string | null
  summary: string | null
  techStack: string[]
  startDate: string | null
  endDate: string | null
  status: string
  source: 'user' | 'ai_suggested' | 'project_sync'
  confirmed: boolean
  createdAt: string
  updatedAt: string
}

export interface ProjectEntryInput {
  name: string
  role?: string | null
  summary?: string | null
  techStack?: string[]
  startDate?: string | null
  endDate?: string | null
  status?: string
}

export interface TimelineEvent {
  id: number
  eventDate: string
  title: string
  description: string | null
  type: TimelineType
  source: 'user' | 'ai_suggested'
  confirmed: boolean
  createdAt: string
}

export interface TimelineInput {
  eventDate: string
  title: string
  description?: string | null
  type?: TimelineType
}

export interface PendingSuggestion {
  id: number
  kind: SuggestionKind
  refKey: string
  title: string
  payload: Record<string, unknown>
  status: SuggestionStatus
  createdAt: string
  decidedAt: string | null
}

export interface ProfileOverview {
  basic: ProfileBasic
  skills: ProfileSkill[]
  projects: ProfileProjectEntry[]
  timeline: TimelineEvent[]
  suggestions: PendingSuggestion[]
  pendingCount: number
  rejectedKinds: SuggestionKind[]
}

const listQ = (confirmedOnly?: boolean) =>
  confirmedOnly == null ? '' : `?confirmedOnly=${confirmedOnly}`

// ---------------------------------------------------------------- 总览

export async function overview(): Promise<ProfileOverview> {
  if (inTauri()) return invokeCore<ProfileOverview>('profile_overview')
  return request<ProfileOverview>('/api/v1/profile')
}

// ---------------------------------------------------------------- 基础信息

export async function basicGet(): Promise<ProfileBasic> {
  if (inTauri()) return invokeCore<ProfileBasic>('profile_basic_get')
  return request<ProfileBasic>('/api/v1/profile/basic')
}

export async function basicSave(input: BasicInput): Promise<ProfileBasic> {
  if (inTauri()) return invokeCore<ProfileBasic>('profile_basic_save', { input })
  return request<ProfileBasic>('/api/v1/profile/basic', {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

// ---------------------------------------------------------------- 技能

export async function skills(confirmedOnly?: boolean): Promise<ProfileSkill[]> {
  if (inTauri())
    return invokeCore<ProfileSkill[]>('profile_skills_list', { confirmedOnly })
  return request<ProfileSkill[]>(`/api/v1/profile/skills${listQ(confirmedOnly)}`)
}

export async function skillAdd(input: SkillInput): Promise<ProfileSkill> {
  if (inTauri()) return invokeCore<ProfileSkill>('profile_skill_add', { input })
  return request<ProfileSkill>('/api/v1/profile/skills', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function skillEdit(id: number, patch: SkillPatch): Promise<ProfileSkill> {
  if (inTauri()) return invokeCore<ProfileSkill>('profile_skill_update', { id, patch })
  return request<ProfileSkill>(`/api/v1/profile/skills/${id}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export async function skillRemove(id: number): Promise<void> {
  if (inTauri()) return invokeCore<void>('profile_skill_remove', { id })
  return request<void>(`/api/v1/profile/skills/${id}`, { method: 'DELETE' })
}

export async function skillConfirm(id: number): Promise<ProfileSkill> {
  if (inTauri()) return invokeCore<ProfileSkill>('profile_skill_confirm', { id })
  return request<ProfileSkill>(`/api/v1/profile/skills/${id}/confirm`, { method: 'POST' })
}

// ---------------------------------------------------------------- 项目经历

export async function projects(confirmedOnly?: boolean): Promise<ProfileProjectEntry[]> {
  if (inTauri())
    return invokeCore<ProfileProjectEntry[]>('profile_projects_list', { confirmedOnly })
  return request<ProfileProjectEntry[]>(`/api/v1/profile/projects${listQ(confirmedOnly)}`)
}

export async function projectAdd(input: ProjectEntryInput): Promise<ProfileProjectEntry> {
  if (inTauri()) return invokeCore<ProfileProjectEntry>('profile_project_add', { input })
  return request<ProfileProjectEntry>('/api/v1/profile/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function projectRemove(id: number): Promise<void> {
  if (inTauri()) return invokeCore<void>('profile_project_remove', { id })
  return request<void>(`/api/v1/profile/projects/${id}`, { method: 'DELETE' })
}

export async function projectConfirm(id: number): Promise<ProfileProjectEntry> {
  if (inTauri()) return invokeCore<ProfileProjectEntry>('profile_project_confirm', { id })
  return request<ProfileProjectEntry>(`/api/v1/profile/projects/${id}`, { method: 'POST' })
}

// ---------------------------------------------------------------- 时间线

export async function timeline(confirmedOnly?: boolean): Promise<TimelineEvent[]> {
  if (inTauri())
    return invokeCore<TimelineEvent[]>('profile_timeline_list', { confirmedOnly })
  return request<TimelineEvent[]>(`/api/v1/profile/timeline${listQ(confirmedOnly)}`)
}

export async function timelineAdd(input: TimelineInput): Promise<TimelineEvent> {
  if (inTauri()) return invokeCore<TimelineEvent>('profile_timeline_add', { input })
  return request<TimelineEvent>('/api/v1/profile/timeline', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function timelineRemove(id: number): Promise<void> {
  if (inTauri()) return invokeCore<void>('profile_timeline_remove', { id })
  return request<void>(`/api/v1/profile/timeline/${id}`, { method: 'DELETE' })
}

export async function timelineConfirm(id: number): Promise<TimelineEvent> {
  if (inTauri()) return invokeCore<TimelineEvent>('profile_timeline_confirm', { id })
  return request<TimelineEvent>(`/api/v1/profile/timeline/${id}`, { method: 'POST' })
}

// ---------------------------------------------------------------- 待确认建议

export async function suggestions(status?: SuggestionStatus): Promise<PendingSuggestion[]> {
  const q = status ? `?status=${status}` : ''
  if (inTauri()) return invokeCore<PendingSuggestion[]>('profile_suggestions_list', { status })
  return request<PendingSuggestion[]>(`/api/v1/profile/suggestions${q}`)
}

/** 扫描式采集（高频软件 → 技能建议）。返回新增条数。 */
export async function scan(): Promise<number> {
  if (inTauri()) {
    const r = await invokeCore<{ added: number }>('profile_suggestions_scan')
    return r.added
  }
  const r = await request<{ added: number }>('/api/v1/profile/suggestions/scan', {
    method: 'POST',
  })
  return r.added
}

/** 确认建议（单个或批量）——**必须由用户点击触发**。 */
export async function confirm(ids: number[]): Promise<number> {
  if (ids.length === 0) return 0
  if (inTauri()) {
    const r = await invokeCore<{ confirmed: number }>('profile_suggestions_confirm', { ids })
    return r.confirmed
  }
  const r = await request<{ confirmed: number }>('/api/v1/profile/suggestions/confirm', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })
  return r.confirmed
}

export async function ignore(ids: number[]): Promise<number> {
  if (ids.length === 0) return 0
  if (inTauri()) {
    const r = await invokeCore<{ ignored: number }>('profile_suggestions_ignore', { ids })
    return r.ignored
  }
  const r = await request<{ ignored: number }>('/api/v1/profile/suggestions/ignore', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })
  return r.ignored
}

/** 永久拒绝某类建议（10 §5 用户权利之四）。 */
export async function rejectKind(kind: SuggestionKind): Promise<number> {
  if (inTauri()) {
    const r = await invokeCore<{ ignored: number }>('profile_suggestions_reject_kind', { kind })
    return r.ignored
  }
  const r = await request<{ ignored: number }>('/api/v1/profile/suggestions/reject-kind', {
    method: 'POST',
    body: JSON.stringify({ kind }),
  })
  return r.ignored
}

// ---------------------------------------------------------------- 导出

export async function exportMarkdown(): Promise<string> {
  if (inTauri()) {
    const r = await invokeCore<{ markdown: string }>('profile_export_markdown')
    return r.markdown
  }
  const r = await request<{ markdown: string }>('/api/v1/profile/export/markdown')
  return r.markdown
}

export const profileApi = {
  overview,
  basicGet,
  basicSave,
  skills,
  skillAdd,
  skillEdit,
  skillRemove,
  skillConfirm,
  projects,
  projectAdd,
  projectRemove,
  projectConfirm,
  timeline,
  timelineAdd,
  timelineRemove,
  timelineConfirm,
  suggestions,
  scan,
  confirm,
  ignore,
  rejectKind,
  exportMarkdown,
}
