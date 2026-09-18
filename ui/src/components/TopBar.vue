<script setup lang="ts">
/**
 * 顶栏（UI-FUSION 第四轮 · appbar 化）。
 *
 * 结构对齐原型 `personal-workspace-ui/index.html` 的 `.titlebar`：
 *   .tb-mark（logo + 标题）→ .tb-sep → .tb-context（所在页面）→ .tb-spacer
 *   → 右侧动作区（主题 / 最小化 / 设置）
 * 样式全部落在 `ui/src/styles/base.css`（壳层段），本文件只出结构。
 *
 * 保留的验收依赖（不可删）：
 *  - `verify_stage1.py` 2b：DOM 必须含「设置」「最小化」两串文本（见 topbar 动作区）；
 *  - `verify_stage1.py`：`a[href="/settings"]` 导航入口（侧栏 nav-foot 也有一处）。
 *
 * 未接原型 `.win-btns` 的最大化/关闭：本应用保留原生窗口装饰
 * （`core/tauri.conf.json` 未关 decorations），无需自绘窗口按钮。
 */
import { computed, onMounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { connection, inTauri, invokeCore } from '@/api/client'
import { PAGE_TITLES } from '@/router'
import { useSettingsStore } from '@/stores/settings'
import { logger } from '@/utils/logger'

const settings = useSettingsStore()
const route = useRoute()
onMounted(() => settings.load())

/**
 * 最小化主窗口（04 §2 顶栏 `[设置] [最小化]`）。
 *
 * 补完 REVIEW-002 R-06：此前 core 侧 `minimize_window` 命令**已经存在**，
 * 但 UI 零调用 —— 属"命令在、按钮没接"的半成品，功能实际不可用。
 * 通道按 ADR-001 归 Rust（core 的 `minimize_window`），前端只发这一个无参数动作。
 *
 * 浏览器直开（vite dev，无 Tauri 容器）时没有窗口可最小化 ⇒ 按钮置灰，
 * 而不是点了没反应（失败要可见，不能静默）。
 */
const canMinimize = inTauri()

async function onMinimize(): Promise<void> {
  try {
    await invokeCore<void>('minimize_window')
  } catch (err) {
    logger.error('window', `minimize_window 失败：${String(err)}`)
  }
}

/** 顶栏上下文（原型 `.tb-context`）：当前所在页面，与窗口标题同源（PAGE_TITLES）。 */
const pageLabel = computed(() => PAGE_TITLES[String(route.name ?? '')] ?? '我的电脑')

/**
 * 主题切换（原型 titlebar 的 `#themeBtn`）：写同一个 `ui.theme` 键，与设置页共用 store。
 *
 * ★ 读的是 store 的 `resolved`（实际生效的明暗）而不是 `data.theme`：
 *   "跟随系统"档下 `data.theme === 'system'`，用它判色会让图标在
 *   "跟随系统 + 系统是深色"时显示成浅色，点一下还会把显式选择写成 light。
 *   设计稿 `themeBtn` 的判据原文就是 `documentElement.dataset.theme`，同义。
 */
const isDark = computed(() => settings.resolved === 'dark')

async function toggleTheme(): Promise<void> {
  try {
    await settings.toggleTheme()
  } catch (err) {
    logger.error('theme', `切换主题失败：${String(err)}`)
  }
}
</script>

<template>
  <header class="app-topbar">
    <!-- 原型 .tb-mark：logo（原型 .tb-logo path 原文）+ 应用名 -->
    <div class="tb-mark">
      <svg class="tb-logo" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          class="tb-logo__edge"
          d="M9.6 6V5.2A2.2 2.2 0 0 1 11.8 3h6.4A2.2 2.2 0 0 1 20.4 5.2v6.4A2.2 2.2 0 0 1 18.2 14h-.8"
          stroke-width="1.8"
          stroke-linecap="round"
        />
        <rect class="tb-logo__fill" x="3.6" y="8" width="11" height="12" rx="2.2" />
        <path class="tb-logo__line" d="M6.8 12h4.6" stroke-width="1.6" stroke-linecap="round" />
      </svg>
      <span class="tb-title">Personal Workspace</span>
    </div>

    <span class="tb-sep"></span>

    <!-- 原型 .tb-context：机器 → 当前页（原型 run 态用同一形态的 span + ‹·›） -->
    <div class="tb-context" title="当前所在的页面">
      <span>我的电脑</span>
      <span class="tb-dot">·</span>
      <span>{{ pageLabel }}</span>
    </div>

    <span class="tb-sep"></span>

    <!-- appbar 中段（由 App.vue 注入 = 模式栏；放在 spacer **之前**，
         这样右侧动作区才会被推到 appbar 最右缘） -->
    <slot />

    <span class="tb-spacer"></span>

    <span
      v-if="!connection.online"
      class="tb-degraded"
      title="core 未连接，所有持久化降级到本地"
    >⚠ 降级模式</span>

    <div class="tb-actions">
      <button
        type="button"
        class="tb-btn"
        :title="isDark ? '切换到浅色主题' : '切换到深色主题'"
        @click="toggleTheme"
      >{{ isDark ? '浅色' : '深色' }}</button>

      <button
        type="button"
        class="tb-btn"
        :disabled="!canMinimize"
        :title="canMinimize ? '最小化' : '浏览器环境下无窗口可最小化'"
        @click="onMinimize"
      >最小化</button>

      <RouterLink class="tb-btn" to="/settings" title="设置">设置</RouterLink>
    </div>
  </header>
</template>
