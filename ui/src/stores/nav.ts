import { defineStore } from 'pinia'

import { configApi } from '@/api/configService'

const KEY = 'ui.nav.collapsed'

export const useNavStore = defineStore('nav', {
  state: () => ({
    collapsed: false,
    loaded: false,
  }),
  actions: {
    async load() {
      if (this.loaded) return
      const value = await configApi.get<boolean>(KEY, false)
      this.collapsed = value
      this.loaded = true
    },
    async toggle() {
      this.collapsed = !this.collapsed
      await configApi.put(KEY, this.collapsed)
    },
  },
})