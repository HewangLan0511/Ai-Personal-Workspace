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
    /**
     * 显式设置折叠态。
     *
     * 为什么需要：壳层的拖拽折叠阈值与窗口档位状态机（`useShellLayout`）要的是
     * "确保是收起的"，而不是"切一下"。用 `toggle` 代替会在重复调用时来回抖，
     * 也会在"已经是收起态"时误展平。
     */
    async setCollapsed(v: boolean) {
      if (this.collapsed === v) return
      this.collapsed = v
      await configApi.put(KEY, v)
    },
  },
})