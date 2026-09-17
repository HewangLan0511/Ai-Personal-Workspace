<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

import NavSide from '@/components/NavSide.vue'
import AiSidebar from '@/components/AiSidebar.vue'
import ModeBar from '@/components/ModeBar.vue'
import StatusBar from '@/components/StatusBar.vue'
import TopBar from '@/components/TopBar.vue'
import ToastHost from '@/components/ToastHost.vue'
import { checkConnection } from '@/api/client'
import { startEventBridge, stopEventBridge } from '@/api/eventBridge'
import { useNavStore } from '@/stores/nav'
import { useSettingsStore } from '@/stores/settings'
import { createPageTransitionHooks } from '@/motion'

const nav = useNavStore()
const settings = useSettingsStore()
// TECH-01 §十五：content-only 页面过渡（latest-wins），业务零感知。
const pageTransition = createPageTransitionHooks()

onMounted(async () => {
  await Promise.all([nav.load(), settings.load()])
  await checkConnection()
  // L-017 / L-032：建立 core → webview 的唯一事件监听通道
  await startEventBridge()
})

onUnmounted(() => {
  stopEventBridge()
})
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <!-- 模式栏（06 §5 F-40）：常驻显示当前模式 + 快速切换 -->
    <ModeBar />
    <NavSide />
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition :css="false" @enter="pageTransition.onEnter" @leave="pageTransition.onLeave">
          <component :is="Component" :key="$route.path" />
        </transition>
      </router-view>
    </main>
    <!-- AI 侧栏（08 §5）：右侧可收起、宽度可拖拽且持久化 -->
    <AiSidebar />
    <StatusBar />
    <!-- 统一 Toast 宿主（TECH-03-B §二）：全应用唯一的提示渲染者 -->
    <ToastHost />
  </div>
</template>