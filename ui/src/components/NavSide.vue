<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'

import { useNavStore } from '@/stores/nav'

const nav = useNavStore()
onMounted(() => nav.load())

interface NavEntry {
  to: string
  label: string
}

const entries: NavEntry[] = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/ai', label: 'AI' },
  { to: '/learning', label: '学习' },
  { to: '/project', label: '项目' },
  { to: '/profile', label: '档案' },
  { to: '/life', label: '生活' },
  { to: '/device', label: '设备' },
]
</script>

<template>
  <aside class="app-nav" :class="{ collapsed: nav.collapsed }">
    <div style="display: flex; justify-content: flex-end; padding: 6px 8px;">
      <button
        type="button"
        :aria-label="nav.collapsed ? '展开侧栏' : '折叠侧栏'"
        :title="nav.collapsed ? '展开' : '折叠'"
        @click="nav.toggle()"
      >
        <span v-if="nav.collapsed">▶</span>
        <span v-else>◀</span>
      </button>
    </div>
    <nav class="nav-list">
      <RouterLink
        v-for="entry in entries"
        :key="entry.to"
        :to="entry.to"
        class="nav-item"
        active-class="router-link-active"
      >
        <span class="nav-label">{{ entry.label }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>