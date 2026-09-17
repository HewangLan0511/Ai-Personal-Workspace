/**
 * 生活中心 API 封装（阶段8 · `11-阶段指令-生活与设备.md` §A）。
 *
 * 通道：Tauri invoke 为主，HTTP `/api/v1/life/*` 为备用。
 * 天气 / 音乐 / 社交的实现在 Python sidecar，core 只做代理 —— 本文件是纯封装层。
 */

import { inTauri, invokeCore, request } from './client'

export interface UsageRankRow {
  app_name: string
  seconds: number
}

export interface UsageToday {
  day: string
  totalSeconds: number
  ranking: UsageRankRow[]
}

export interface WeatherDay {
  date: string
  weather: string
  max: number | null
  min: number | null
}

export interface WeatherInfo {
  ok?: boolean
  reason?: string
  message?: string
  city: string
  source: string
  current: { temperature: number | null; weather: string }
  daily: WeatherDay[]
}

export interface MediaSession {
  available: boolean
  reason?: string
  session: {
    title: string
    artist: string
    album: string
    status: string
    position_seconds: number
    duration_seconds: number
  } | null
}

export interface SocialItem {
  name: string
  type: string
  ok: boolean
  unread?: number
  summary?: string
}

export interface SocialOverview {
  items: SocialItem[]
  note: string
}

export interface SocialServiceConfig {
  name: string
  type: 'imap' | 'demo'
  host?: string
  port?: number
  user?: string
  credRef?: string
  tls?: boolean
  demoUnread?: number
}

// ---------------------------------------------------------------- 使用时长（A4）

export async function usageToday(): Promise<UsageToday> {
  if (inTauri()) return invokeCore<UsageToday>('life_usage_today')
  return request<UsageToday>('/api/v1/life/usage/today')
}

export interface UsageWeek {
  days: { day: string; total: number }[]
}

export async function usageWeek(): Promise<UsageWeek> {
  if (inTauri()) return invokeCore<UsageWeek>('life_usage_week')
  return request<UsageWeek>('/api/v1/life/usage/week')
}

// ---------------------------------------------------------------- 天气（A1）

export async function weather(city?: string): Promise<WeatherInfo> {
  if (inTauri()) return invokeCore<WeatherInfo>('life_weather', { city: city ?? null })
  return request<WeatherInfo>(`/api/v1/life/weather${city ? `?city=${encodeURIComponent(city)}` : ''}`)
}

// ---------------------------------------------------------------- 音乐（A2）

export async function mediaNow(): Promise<MediaSession> {
  if (inTauri()) return invokeCore<MediaSession>('life_media_now')
  return request<MediaSession>('/api/v1/life/media')
}

export async function mediaControl(action: 'play' | 'pause' | 'next' | 'previous'): Promise<{ acted: boolean }> {
  if (inTauri()) return invokeCore<{ acted: boolean }>('life_media_control', { action })
  return request<{ acted: boolean }>('/api/v1/life/media/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  })
}

// ---------------------------------------------------------------- 社交概览（A3）

export async function socialOverview(): Promise<SocialOverview> {
  if (inTauri()) return invokeCore<SocialOverview>('life_social_overview')
  return request<SocialOverview>('/api/v1/life/social/overview')
}

export async function socialConfigGet(): Promise<{ services: SocialServiceConfig[] }> {
  if (inTauri()) return invokeCore<{ services: SocialServiceConfig[] }>('life_social_config_get')
  return request<{ services: SocialServiceConfig[] }>('/api/v1/life/social/config')
}

export async function socialConfigPut(services: SocialServiceConfig[]): Promise<void> {
  if (inTauri()) {
    await invokeCore('life_social_config_put', { services })
    return
  }
  await request('/api/v1/life/social/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ services }),
  })
}

/** 聚合出口（与 profileApi 同风格，视图统一从这里取）。 */
export const lifeApi = {
  usageToday,
  usageWeek,
  weather,
  mediaNow,
  mediaControl,
  socialOverview,
  socialConfigGet,
  socialConfigPut,
}
