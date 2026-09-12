<script setup lang="ts">
import { onMounted } from 'vue'

import { useSettingsStore } from '@/stores/settings'
import { connection } from '@/api/client'

const settings = useSettingsStore()
onMounted(() => settings.load())
</script>

<template>
  <header class="app-topbar">
    <strong>Personal Workspace</strong>
    <div class="topbar-right" style="display: flex; gap: 10px; align-items: center;">
      <span
        v-if="!connection.online"
        style="color: var(--danger); font-size: 12px;"
        title="core 未连接，所有持久化降级到本地"
      >⚠ 降级模式</span>
      <router-link to="/settings">
        <button>设置</button>
      </router-link>
    </div>
  </header>
</template>