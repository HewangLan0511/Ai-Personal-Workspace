import { defineStore } from 'pinia'

import { configApi } from '@/api/configService'
import type { Settings } from '@/api/types'

/** 主题值（设计稿「设置 · 外观」的三档分段控件）。 */
export type ThemeChoice = Settings['theme']

const DEFAULTS: Settings = {
  theme: 'light',
  autostart: false,
  defaultProvider: '',
  dataDir: '',
  privacy: false,
}

const KEY_PREFIX = ''

function key(name: keyof Settings): string {
  return `${KEY_PREFIX}${SETTING_KEYS[name]}`
}

const SETTING_KEYS: Record<keyof Settings, string> = {
  theme: 'ui.theme',
  autostart: 'app.autostart',
  defaultProvider: 'ai.default_provider',
  dataDir: 'app.data_dir',
  privacy: 'privacy.telemetry',
}

/**
 * 主题落地（设计稿 `setTheme()` 逐字对应）。
 *
 * ★ 关键一条（设计稿注释原文）：`system` 是**选择**，不是 `data-theme` 的值 ——
 *   必须先把 `system` 解析成 `light|dark`，再把**解析结果**写进 `data-theme`。
 *   设计稿为这条踩过坑："设置里切主题没反应"就是因为漏了 `dataset.theme` 只改了 state。
 *   tokens.css 的深色块选择器是 `[data-theme='dark']`，写 `data-theme="system"` 等于没切。
 *
 * ★ 跟随系统需要**监听系统变化**：选了"跟随系统"之后用户在外面改了系统主题，
 *   应用要跟着变。监听器只在 theme === 'system' 时生效（其他档位下系统变化与应用无关），
 *   并且同一条监听器只挂一次。
 */
let systemWatch: ((ev: MediaQueryListEvent) => void) | null = null
let media: MediaQueryList | null = null
/** 当前选择（模块级镜像）—— 供系统主题监听器读取，避免在回调里再取 store。 */
let currentTheme: ThemeChoice = 'light'

function prefersDark(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  if (!media) media = window.matchMedia('(prefers-color-scheme: dark)')
  return media.matches
}

/** 把主题选择解析成真正要落到 `data-theme` 的值。 */
export function resolveTheme(theme: ThemeChoice): 'light' | 'dark' {
  return theme === 'system' ? (prefersDark() ? 'dark' : 'light') : theme
}

function applyTheme(theme: ThemeChoice): void {
  currentTheme = theme
  document.documentElement.dataset['theme'] = resolveTheme(theme)
}

/** 按当前选择决定是否监听系统主题变化（幂等：只挂一次监听器）。 */
function syncSystemWatch(): void {
  if (typeof window === 'undefined' || !window.matchMedia) return
  if (!media) media = window.matchMedia('(prefers-color-scheme: dark)')
  if (systemWatch) return
  systemWatch = () => {
    // 只在"跟随系统"档位下响应；其他档位忽略（系统变化与显式选择无关）
    if (currentTheme !== 'system') return
    applyTheme('system')
    const s = useSettingsStore()
    s.resolved = resolveTheme('system')
  }
  media.addEventListener('change', systemWatch)
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    data: { ...DEFAULTS } as Settings,
    /**
     * 当前**实际生效**的明暗（`data-theme` 的值）。
     * 与 `data.theme` 的区别只在"跟随系统"档：`data.theme === 'system'` 时
     * 它是解析结果，且会随系统主题变化更新 —— 顶栏图标读它才不会在
     * "跟随系统 + 系统是深色"时显示成浅色。
     */
    resolved: 'light' as 'light' | 'dark',
    loaded: false,
    savedAt: 0,
  }),
  actions: {
    async load() {
      if (this.loaded) return
      const [theme, autostart, defaultProvider, dataDir, privacy] = await Promise.all([
        configApi.get<ThemeChoice>(SETTING_KEYS.theme, DEFAULTS.theme),
        configApi.get<boolean>(SETTING_KEYS.autostart, DEFAULTS.autostart),
        configApi.get<string>(SETTING_KEYS.defaultProvider, DEFAULTS.defaultProvider),
        configApi.get<string>(SETTING_KEYS.dataDir, DEFAULTS.dataDir),
        configApi.get<boolean>(SETTING_KEYS.privacy, DEFAULTS.privacy),
      ])
      // 存量库里可能是 'light'/'dark'（两档时代写入的），照常接受
      this.data = {
        theme: theme === 'dark' || theme === 'system' ? theme : 'light',
        autostart,
        defaultProvider,
        dataDir,
        privacy,
      }
      applyTheme(this.data.theme)
      this.resolved = resolveTheme(this.data.theme)
      syncSystemWatch()
      this.loaded = true
    },
    /**
     * 切主题（设计稿 `setTheme(v)`）：三档都走这里 ——
     * 标题栏那枚按钮与设置里的分段控件**共用同一个函数**，不允许各写一份。
     */
    async setTheme(theme: ThemeChoice) {
      this.data.theme = theme
      applyTheme(theme)
      this.resolved = resolveTheme(theme)
      syncSystemWatch()
      await configApi.put(key('theme'), theme)
      this.savedAt = Date.now()
    },
    /** 标题栏按钮：在**当前实际颜色**上取反（浅 ⇄ 深），显式落成 light|dark。 */
    async toggleTheme() {
      await this.setTheme(this.resolved === 'dark' ? 'light' : 'dark')
    },
    async savePartial(patch: Partial<Settings>): Promise<void> {
      Object.assign(this.data, patch)
      await Promise.all(
        (Object.keys(patch) as Array<keyof Settings>).map((k) =>
          configApi.put(key(k), this.data[k]),
        ),
      )
      this.savedAt = Date.now()
    },
  },
})
