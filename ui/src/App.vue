<script setup lang="ts">
/**
 * 应用壳层（设计稿 `.shell` + `main.panel`）
 * =========================================
 *
 * 唯一视觉来源 = `personal-workspace-ui/index.html`。DOM 结构逐字对应：
 * ```
 * <div class="shell" data-cw="lg|md|sm|xs" data-rs="full|compact|collapsed|fallback">
 *   <header class="titlebar">…</header>
 *   <main class="panel">
 *     <aside class="sidebar">…</aside>
 *     <section class="content">
 *       <div class="view">…</div>
 *     </section>
 *     <aside class="widget-col">…</aside>
 *     <aside class="ai-dock">…</aside>
 *   </main>
 * </div>
 * ```
 *
 * ★ 双类名（`app-shell shell` / `app-panel panel` / `app-content content` /
 *   `app-main view`）：设计稿的 `.shell` / `.panel` / `.content` / `.view` /
 *   `.shell[data-cw=…]` / `.shell[data-rs=…]` / `.shell.mini` / `.shell.cinema`
 *   规则**原样命中真实元素**，几何只有一份事实来源（base.css 的 UI-FUSION-FULL 段）。
 *   `.app-*` 只作工程钩子：验收脚本的 `querySelector`、以及 base.css 里那几条
 *   无法从原型转写的适配（见 base.css 壳层注释）。
 *
 * ★ 本工程相对原型的**唯一结构差异**：`.content` 里多一条 `.app-status` 状态条
 *   （承载 core 连接态，原型无此件）。它 `flex:0 0 auto` 贴在内容列底部，
 *   不影响 `.view` 的滚动与四列几何。
 *
 * ★ 壳层状态是**单例**（`useShellLayout()`）：宽度 / `data-cw` / `data-rs` /
 *   组件区折叠由本组件 owner 化地 `init()` / `destroy()`；子组件只读同一份。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AiSidebar from '@/components/AiSidebar.vue'
import CtxMenu from '@/components/CtxMenu.vue'
import ModeBar from '@/components/ModeBar.vue'
import NavSide from '@/components/NavSide.vue'
import StatusBar from '@/components/StatusBar.vue'
import ToastHost from '@/components/ToastHost.vue'
import TopBar from '@/components/TopBar.vue'
import WidgetCol from '@/components/WidgetCol.vue'
import { checkConnection } from '@/api/client'
import { startEventBridge, stopEventBridge } from '@/api/eventBridge'
import { useShellLayout } from '@/composables/useShellLayout'
import { useNavStore } from '@/stores/nav'
import { useSettingsStore } from '@/stores/settings'
import { useWidgetColStore } from '@/stores/widgetCol'
import { createPageTransitionHooks } from '@/motion'

const nav = useNavStore()
const settings = useSettingsStore()
const widgetCol = useWidgetColStore()
const shell = useShellLayout()
// TECH-01 §十五：content-only 页面过渡（latest-wins），业务零感知。
const pageTransition = createPageTransitionHooks()

const route = useRoute()
/** 运行页 = 沉浸态（设计稿 `.shell.cinema`）。 */
const isRun = computed(() => route.path === '/run')

const shellEl = ref<HTMLElement | null>(null)

/**
 * 运行页的沉浸态编排（原型 `go()` + `render()` 里的 `if(isRun)` 两处）：
 *   · `.cinema` **提前一拍**切换（不等场景离场），否则组件区比侧栏晚 80ms 收，
 *     窗口 120ms 落位时会撞上"右边还在变宽"；
 *   · 等 RunView 挂载（`nextTick`）后再播 `playCinema()` —— 原型是同步写
 *     innerHTML 后立刻播，本工程是组件挂载，必须等 DOM 就位，否则
 *     `.stage .win` 一个都取不到，`--i` 序号与入场动画都会丢。
 */
watch(
  () => route.path,
  async (p) => {
    const on = p === '/run'
    shell.setCinema(on)
    if (!on) return
    await nextTick()
    shell.playCinema()
  },
)

/**
 * 手柄挂载 —— 与原型 `mountHandles()` 同一口径：
 * 手柄是**容器**的子节点，行为在挂载时按 `.rsh--<key>` 查一次绑上
 * （不是组件内部自带行为 —— 容器重绘会重建组件实例，拖到一半的指针捕获就丢了）。
 * AI 档不在此列：它的手柄由 `AiSidebar` 自己持有（TECH-03-B §一 的
 * `claim('drag')` 三件套在那份文件里被冻结验收）。
 */
async function mountHandles(): Promise<void> {
  await nextTick()
  const root = shellEl.value
  if (!root) return
  shell.attachHandle('nav', root.querySelector<HTMLElement>('.rsh--nav'))
  shell.attachHandle('widget', root.querySelector<HTMLElement>('.rsh--widget'))
}

onMounted(async () => {
  shell.attachShell(shellEl.value)
  await shell.init()
  await Promise.all([nav.load(), settings.load(), widgetCol.load()])
  await mountHandles()
  // 深链直达运行页：路由不会"变"，watch 不会触发 —— 这里补一次初始沉浸态
  shell.setCinema(isRun.value)
  if (isRun.value) {
    await nextTick()
    shell.playCinema()
  }
  await checkConnection()
  // L-017 / L-032：建立 core → webview 的唯一事件监听通道
  await startEventBridge()
})

onUnmounted(() => {
  shell.destroy()
  stopEventBridge()
})
</script>

<template>
  <!-- 壳层 = 原型「窗口即纸面」：外层窗口底 → 内缩工作台面板 → 面板内四区。
       `data-cw`（内容分档）与 `data-rs`（chrome 策略）由 useShellLayout 按
       原型 initRS 的阈值与滞回带写入，样式在 base.css 里按属性选择器分流。
       `mini`（导航图标态）与 `cinema`（沉浸态）是设计稿的两个壳层状态类。 -->
  <div
    ref="shellEl"
    class="app-shell shell"
    :class="{ mini: nav.collapsed, cinema: shell.cinema.value }"
    :style="shell.shellStyle.value"
    :data-cw="shell.cw.value || undefined"
    :data-rs="shell.rs.value"
  >
    <!-- 顶栏 appbar（原型 .titlebar，高 --titlebar-h=44）：单条承载
         品牌 / 上下文 / 模式栏 / 窗口动作。 -->
    <header class="app-titlebar">
      <TopBar>
        <!-- 模式栏（06 §5 F-40）：常驻当前模式 + 快速切换。
             注入 appbar 中段（在 spacer 之前），右侧动作区因此贴右缘。 -->
        <ModeBar />
      </TopBar>
    </header>

    <!-- 工作台面板（原型 main.panel）：四区同处一块 20px 圆角面板，
         四周内缩 --panel-inset。顺序与原型一致：
         .sidebar | .content(.view) | .widget-col | .ai-dock -->
    <div class="app-panel panel">
      <NavSide />

      <div class="app-content content">
        <main class="app-main view" :class="{ noscroll: isRun }">
          <router-view v-slot="{ Component }">
            <transition :css="false" @enter="pageTransition.onEnter" @leave="pageTransition.onLeave">
              <component :is="Component" :key="$route.path" />
            </transition>
          </router-view>
        </main>
        <!-- 状态条（本工程独有，见文件头注释）：不参与滚动 -->
        <StatusBar />
      </div>

      <!-- 插件组件侧挂区（原型 .widget-col）：内容区与 AI 侧栏之间的可编排区 -->
      <WidgetCol />

      <!-- AI 侧栏（原型 .ai-dock，08 §5）：右侧可收起、宽度可拖拽且持久化 -->
      <AiSidebar />
    </div>

    <!-- 统一 Toast 宿主（TECH-03-B §二）：全应用唯一的提示渲染者 -->
    <ToastHost />
    <!-- 右键菜单宿主（设计稿 #ctxMenu）：挂在 body 上的单例浮层 -->
    <CtxMenu />
    <!-- 静默播报区（原型 #liveRegion）：拖拽/排序这类"结果肉眼可见"的操作
         只进 aria-live，不弹可见提示条（弹了是噪音，还会打断连续拖拽）。 -->
    <div id="pw-live-region" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>
  </div>
</template>
