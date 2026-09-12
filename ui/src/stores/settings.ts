import { defineStore } from 'pinia'

import { configApi } from '@/api/configService'
import type { Settings } from '@/api/types'

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

function applyTheme(theme: 'light' | 'dark'): void {
  document.documentElement.dataset['theme'] = theme
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    data: { ...DEFAULTS } as Settings,
    loaded: false,
    savedAt: 0,
  }),
  actions: {
    async load() {
      if (this.loaded) return
      const [theme, autostart, defaultProvider, dataDir, privacy] = await Promise.all([
        configApi.get<'light' | 'dark'>(SETTING_KEYS.theme, DEFAULTS.theme),
        configApi.get<boolean>(SETTING_KEYS.autostart, DEFAULTS.autostart),
        configApi.get<string>(SETTING_KEYS.defaultProvider, DEFAULTS.defaultProvider),
        configApi.get<string>(SETTING_KEYS.dataDir, DEFAULTS.dataDir),
        configApi.get<boolean>(SETTING_KEYS.privacy, DEFAULTS.privacy),
      ])
      this.data = { theme, autostart, defaultProvider, dataDir, privacy }
      applyTheme(this.data.theme)
      this.loaded = true
    },
    async setTheme(theme: 'light' | 'dark') {
      this.data.theme = theme
      applyTheme(theme)
      await configApi.put(key('theme'), theme)
      this.savedAt = Date.now()
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