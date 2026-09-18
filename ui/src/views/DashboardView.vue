<script setup lang="ts">
/**
 * UI-FUSION-REAL：首页按原型 `#/home` 结构重建（唯一视觉源 = personal-workspace-ui/）。
 *
 * 原型结构：greet 问候行 → Hero 当前工作大卡（唯一 display 级焦点）→ 最近使用
 * （grid-recent app 方块）→ home-split[我的工作空间 / 今天行动中心]。
 *
 * 真实数据面（零 mock）：
 * - 当前工作空间/应用状态 → `workspaceRuntime`（TECH-02 门面，同 WorkspaceStatus）；
 * - 最近使用 → 软件库真实排序（core AppsRepo：pinned → launch_count → last_used_at），
 *   点击 = 真实启动（apps_launch）；失败静默（同 FrequentAppsWidget 约定）；
 * - 今天行动中心 = 既有 WidgetCard 组件区（★ 验收项 8 的使用次数→尺寸链路原样保留）；
 * - WorkspaceStatus 挂在「我的工作空间」区（verify_tech05c T3e 数据来源不变）。
 *
 * 兼容约束：aria-label="Dashboard"（verify_stage1 路由标记）、widget 类族不变。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { lifeApi, type MediaSession } from '@/api/lifeService'
import PwIcon from '@/components/PwIcon.vue'
import WidgetCard from '@/components/WidgetCard.vue'
import HomeHero from '@/components/HomeHero.vue'
import WorkspaceStatus from '@/components/WorkspaceStatus.vue'
import { useAppsStore } from '@/stores/apps'
import { openContextMenu } from '@/composables/useContextMenu'
import { useProfileStore } from '@/stores/profile'
import { useWidgets } from '@/composables/useWidgets'
import { useWidgetStore } from '@/stores/widgets'
import { usePageEntrance } from '@/motion'
// 编排列表拖拽排序（设计稿 `enableSort('#arrangeWidgets', '.arrange-row', …)`）：
// 走同一套 `useListSort`（FLIP 让位 + `.dragging` / `body.is-dragging` / `.just-swap`），
// 不新增第二套拖拽实现。
import { useAutoSort } from '@/composables/useListSort'
import { useShellLayout } from '@/composables/useShellLayout'
import { widgetRegistry } from '@/widgets'

const router = useRouter()
const apps = useAppsStore()
const profile = useProfileStore()
const widgetStore = useWidgetStore()
const { moveUp, moveDown, reorderWidget, toggleEnabled, recordUse } = useWidgets()
// 壳层是单例访问器：这里只为拿 `announce`（静默播报，设计稿同款，不弹可见提示）
const shell = useShellLayout()

// 组件编排列表（`.widget-manage > ul`）：容器即 `.arrange-row` 的**直接父节点**
// —— `move` 模式必须绑在直接父级上，绑错层级 `insertBefore` 会抛 NotFoundError。
const arrangeList = ref<HTMLElement | null>(null)
useAutoSort(arrangeList, computed(() => widgetStore.all.length), {
  itemSelector: '.arrange-row',
  mode: 'move',
  onReorder: (from, to) => {
    void reorderWidget(from, to)
    shell.announce(`组件顺序已调整，第 ${from + 1} 个移到第 ${to + 1} 位`)
  },
})

/**
 * 首屏入场（设计稿 `playEntrance()`）：greet / Hero / 最近使用 / 工作空间区
 * 四块按 `data-enter` 错峰抬起，整段 400–520ms。
 * **每会话只播一次**（设计稿 `homeEntered`）—— 首屏入场是一次"欢迎编排"，
 * 每次翻页都重播会变成噪音；其余三页（档案/设置/软件）是列表页，按需每次播。
 */
const rootEl = ref<HTMLElement | null>(null)
usePageEntrance(rootEl, { once: true, key: 'dashboard' })

onMounted(() => {
  widgetStore.load()
  apps.load()
  void profile.init()
  void loadMedia()
})

// ---------------------------------------------------------------- 问候（greet）

const nickname = computed(() => profile.basic?.name || '')

function greetWord(): string {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function todayText(): string {
  const d = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 · 星期${week} · 准备开始什么？`
}

// ---------------------------------------------------------------- 正在播放（原型 fn:nowPlaying）
//
// 位置说明：设计稿把 `nowPlaying()` 放在 **首页 greet 行右侧**（`ROUTES.home`
// line 2201），而不是生活页。生活页（LifeView）那张卡带进度/时长文本，是工程期的
// 详细版；这里补的是设计稿那一条 `greet` 音乐条，数据同样走 `lifeApi.mediaNow()`
// 的真实 SMTC 会话 —— 没有会话就走 `.nowplaying.idle` 分支，不编造曲目。

const media = ref<MediaSession | null>(null)
const mediaBusy = ref(false)

async function loadMedia(): Promise<void> {
  try {
    media.value = await lifeApi.mediaNow()
  } catch {
    media.value = null
  }
}

async function mediaControl(action: 'play' | 'pause' | 'next' | 'previous'): Promise<void> {
  mediaBusy.value = true
  try {
    await lifeApi.mediaControl(action)
    await loadMedia()
  } finally {
    mediaBusy.value = false
  }
}

const mediaPlaying = computed(() => media.value?.session?.status === 'PLAYING')
const mediaPercent = computed(() => {
  const s = media.value?.session
  if (!s || !s.duration_seconds) return 0
  return Math.max(0, Math.min(100, Math.round((s.position_seconds / s.duration_seconds) * 100)))
})

// ---------------------------------------------------------------- Hero（当前工作）

// Hero 已抽到 HomeHero.vue（verify_tech02 T1c 登记的 workspace/runtime 消费者）

// ---------------------------------------------------------------- 最近使用（grid-recent）

const icons = ref<Record<string, string>>({})
const recent = computed(() => apps.items.slice(0, 6))

onMounted(async () => {
  for (const a of recent.value) {
    if (a.icon && !icons.value[a.icon]) {
      const url = await apps.loadIcon(a.icon)
      if (url) icons.value = { ...icons.value, [a.icon]: url }
    }
  }
})

async function launch(id: number): Promise<void> {
  try {
    await apps.launch(id)
  } catch {
    // 静默（同 FrequentAppsWidget）；软件页会 toast 具体原因
  }
}

/**
 * 最近使用方块右键菜单 —— 设计稿 `ctxMenu()` 在 `.app-square` 上的那一份
 * （`personal-workspace-ui` line 5029–5043），条目与顺序逐项对应。
 *
 * ★ 禁用项的处理：设计稿的「添加到工作空间…」「从最近使用中移除」「高级设置…」
 *   对应本工程**尚未实现**的能力。这里保留条目以维持设计与密度，
 *   但标 `disabled` —— 灰掉但可见，绝不做成"点了没反应"的假按钮。
 *   能力落地后把 disabled 摘掉即可，位置与文案无需改动。
 */
function onAppContext(e: MouseEvent, id: number, name: string): void {
  openContextMenu(e.clientX, e.clientY, [
    { head: name },
    { icon: 'play', label: '启动', onSelect: () => void launch(id) },
    { icon: 'plus', label: '添加到工作空间…', disabled: true },
    { icon: 'grid', label: '在软件页中显示', onSelect: () => void router.push('/software') },
    'sep',
    { icon: 'x', label: '从最近使用中移除', disabled: true },
    'sep',
    { icon: 'settings', label: '高级设置…', disabled: true },
  ])
}

// ---------------------------------------------------------------- 组件区（今天行动中心）

const list = computed(() => widgetStore.ordered)
const manageOpen = ref(false)

async function onUnlock() {
  await widgetStore.unlockLayout()
}
</script>

<template>
  <div ref="rootEl" class="page home" aria-label="Dashboard">
    <!-- greet：原型首页头（无 page-head，问候行是唯一 display 级入口） -->
    <div class="greet" data-enter="hero">
      <div class="greet-main">
        <div class="pw-t-page greet-line">{{ greetWord() }}{{ nickname ? `，${nickname}` : '' }}</div>
        <div class="pw-t-cap greet-date">{{ todayText() }}</div>
      </div>
      <span class="pw-spacer"></span>

      <!-- 正在播放：原型 fn:nowPlaying 的结构（.nowplaying / .meta .ttl .art / .bar / .ctrl） -->
      <div v-if="media?.session" class="nowplaying">
        <span class="app tint4 sm"><PwIcon name="music" :size="16" /></span>
        <span class="meta">
          <span class="ttl">{{ media.session.title }}</span>
          <span class="art">{{ media.session.artist || '未知艺术家' }}</span>
        </span>
        <span class="progress thin bar"><i :style="{ width: `${mediaPercent}%` }"></i></span>
        <span class="ctrl">
          <button
            class="icon-btn sm"
            type="button"
            title="上一首"
            :disabled="mediaBusy"
            @click="mediaControl('previous')"
          >
            <PwIcon name="prev" :size="14" />
          </button>
          <button
            class="icon-btn sm"
            type="button"
            :title="mediaPlaying ? '暂停' : '播放'"
            :disabled="mediaBusy"
            @click="mediaControl(mediaPlaying ? 'pause' : 'play')"
          >
            <PwIcon name="play" :size="16" />
          </button>
          <button
            class="icon-btn sm"
            type="button"
            title="下一首"
            :disabled="mediaBusy"
            @click="mediaControl('next')"
          >
            <PwIcon name="next" :size="14" />
          </button>
        </span>
      </div>
      <button
        v-else
        class="nowplaying idle"
        type="button"
        data-pw-nowplaying-idle
        title="没有正在播放的音乐"
        :disabled="mediaBusy"
        @click="mediaControl('play')"
      >
        <span class="app tint4 sm"><PwIcon name="music" :size="16" /></span>
        <span class="meta">
          <span class="ttl">没有正在播放</span>
          <span class="art">点这里开始</span>
        </span>
      </button>
    </div>

    <!-- Hero：当前工作大卡（唯一视觉焦点；数据经 HomeHero → workspaceRuntime） -->
    <HomeHero data-enter="hero" />

    <!-- 最近使用：真实软件库排序 + 真实启动 -->
    <section class="sec" data-enter="sec">
      <div class="sec-head">
        <div class="pw-t-section pw-grow">最近使用</div>
        <button type="button" class="pw-btn pw-btn--ghost pw-btn--sm" @click="router.push('/software')">
          全部软件
        </button>
      </div>
      <div v-if="recent.length" class="grid grid-recent">
        <button
          v-for="a in recent"
          :key="a.id"
          type="button"
          class="app-square"
          :title="a.name"
          @click="launch(a.id)"
          @contextmenu.prevent="onAppContext($event, a.id, a.name)"
        >
          <img v-if="a.icon && icons[a.icon]" :src="icons[a.icon]" :alt="a.name" class="app-ico" />
          <span v-else class="app-ico app-ico--fallback">{{ a.name.slice(0, 1) }}</span>
          <span class="nm">{{ a.name }}</span>
        </button>
      </div>
      <p v-else class="pw-t-cap">软件库还是空的 —— 到「软件」页添加一个，这里会显示最常用的。</p>
    </section>

    <!-- home-split：左 = 我的工作空间（WorkspaceStatus：状态条 + 模板卡），右 = 今天行动中心 -->
    <div class="grid home-split" data-enter="ws">
      <div class="split-left">
        <WorkspaceStatus />
      </div>
      <div class="split-right">
        <div class="sec-head right-head">
          <div class="pw-t-section pw-grow">今天</div>
          <span v-if="widgetStore.layoutLocked" class="stage-note">已按手动布局固定（不再自动调整尺寸）</span>
          <button v-if="widgetStore.layoutLocked" type="button" class="pw-btn pw-btn--ghost pw-btn--sm" @click="onUnlock">
            恢复自动布局
          </button>
          <button type="button" class="pw-btn pw-btn--ghost pw-btn--sm" @click="manageOpen = !manageOpen">
            {{ manageOpen ? '收起组件管理' : '组件管理' }}
          </button>
        </div>

        <!-- 组件管理：04 §3 enabled 字段的用户入口（文案/结构保持验收探针兼容） -->
        <section v-if="manageOpen" class="widget-manage">
          <p class="hint">
            拖动任意一行可调整顺序；勾选控制显示；使用次数决定自动尺寸（≥3 中卡、≥10 大卡）。手动调序后布局固定，可点上方「恢复自动布局」解冻。
          </p>
          <ul ref="arrangeList">
            <!-- 编排行 = 设计稿 `fn:openCustomize` 的 `.arrange-row`（+ `.off` 表示已关闭）。
                 `draggable` + `.grip` 逐字对应设计稿那一份（`.arrange-row .grip{cursor:grab}`
                 在 base.css 里已经有了，此前只是没有可抓的东西）。 -->
            <li
              v-for="w in widgetStore.all"
              :key="w.id"
              class="arrange-row"
              :class="{ off: !w.enabled }"
              draggable="true"
              :data-wid="w.id"
            >
              <span class="grip" title="拖动排序"><PwIcon name="grip" :size="14" /></span>
              <label>
                <input type="checkbox" :checked="w.enabled" @change="toggleEnabled(w.id)" />
                <span>{{ w.name }}</span>
                <span class="stage-note">使用 {{ widgetStore.usage[w.id] ?? 0 }} 次 · 当前 {{ w.size }}</span>
              </label>
            </li>
          </ul>
        </section>

        <div v-if="list.length === 0" class="empty-state empty-inline">
          <p>没有启用的组件。</p>
          <button type="button" @click="manageOpen = true">打开组件管理</button>
        </div>
        <div v-else class="widget-grid">
          <WidgetCard
            v-for="(widget, index) in list"
            :key="widget.id"
            :widget="widget"
            :index="index"
            :total="list.length"
            :use-count="widgetStore.usage[widget.id] ?? 0"
            @move-up="moveUp"
            @move-down="moveDown"
            @toggle-enabled="toggleEnabled"
            @use="recordUse"
          >
            <component
              :is="widgetRegistry[widget.id] ?? widgetRegistry['fallback']"
              v-bind="{ widget }"
            />
          </WidgetCard>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============ 原型 #/home 视觉（token 消费，零硬编码色值） ============ */

.page {
  max-width: var(--content-max);
  padding: var(--pad-page-t) var(--pad-page-x) var(--f-space-9);
}

/* ---- greet ---- */

.greet {
  display: flex;
  align-items: center;
  gap: var(--f-space-4);
  margin-bottom: var(--f-space-6);
}

.greet-line {
  font-family: var(--font-display);
}

.greet-date {
  margin-top: 2px;
}

/* ---- Hero 样式随 HomeHero.vue（见组件内 scoped） ---- */

/* ---- 区块通用 ---- */

.sec {
  margin-top: var(--gap-section);
}

.sec-head {
  display: flex;
  align-items: center;
  gap: var(--f-space-3);
  margin-bottom: var(--f-space-4);
  flex-wrap: wrap;
}

.grid {
  display: grid;
  gap: var(--gap-card);
}

.grid-recent {
  grid-template-columns: repeat(6, 1fr);
}

/* ---- app 方块（最近使用） ---- */

.app-square {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--f-space-2);
  padding: var(--f-space-3);
  border-radius: var(--r-lg);
  background: transparent;
  border: none;
  transition: background var(--dur-fast) var(--ease-out);
}

.app-square:hover {
  background: var(--surface-2);
}

.app-square:active {
  transform: translateY(1px);
}

.app-ico {
  width: 40px;
  height: 40px;
  border-radius: var(--r-md);
  object-fit: contain;
}

.app-ico--fallback {
  display: grid;
  place-items: center;
  background: var(--surface-3);
  border: 1px solid var(--border-subtle);
  color: var(--text-2);
  font-size: var(--fs-body);
  font-weight: var(--fw-semi);
}

.app-square .nm {
  font-size: var(--fs-caption);
  color: var(--text-2);
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
}

/* ---- home-split ---- */

.home-split {
  grid-template-columns: minmax(0, 2fr) minmax(272px, 1fr);
  align-items: start;
  gap: var(--gap-section);
  margin-top: var(--gap-section);
}

.home-split > div {
  min-width: 0;
}

.split-left :deep(.ws-status) {
  margin-bottom: 0;
}

.right-head {
  margin-bottom: var(--f-space-3);
}

/* ---- 组件网格：右侧单列流（★ 探针依赖的 .widget-card 家族不变） ---- */

.widget-grid {
  display: grid;
  grid-template-columns: 1fr;
  grid-auto-rows: minmax(120px, auto);
  gap: var(--f-space-3);
}

.widget-grid :deep(.widget-card.size-medium) {
  grid-column: span 1;
}

.widget-grid :deep(.widget-card.size-large) {
  grid-column: span 1;
  grid-row: span 2;
}

.empty-inline {
  height: auto;
  padding: var(--f-space-6) 0;
}

/* ---- 响应式（原型 data-cw 规则：堆叠不删除） ---- */

@media (max-width: 1080px) {
  .grid-recent {
    grid-template-columns: repeat(3, 1fr);
  }

  .home-split {
    grid-template-columns: minmax(0, 1.6fr) minmax(272px, 1fr);
  }
}

@media (max-width: 900px) {
  .home-split {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .grid-recent {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
