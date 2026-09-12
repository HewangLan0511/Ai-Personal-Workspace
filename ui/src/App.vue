<script setup lang="ts">
import { onMounted } from 'vue'

import NavSide from '@/components/NavSide.vue'
import StatusBar from '@/components/StatusBar.vue'
import TopBar from '@/components/TopBar.vue'
import { checkConnection } from '@/api/client'
import { useNavStore } from '@/stores/nav'
import { useSettingsStore } from '@/stores/settings'

const nav = useNavStore()
const settings = useSettingsStore()

onMounted(async () => {
  await Promise.all([nav.load(), settings.load()])
  await checkConnection()
})
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <NavSide />
    <main class="app-main">
      <router-view />
    </main>
    <StatusBar />
  </div>
</template>