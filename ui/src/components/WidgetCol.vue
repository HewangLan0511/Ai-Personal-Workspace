<script setup lang="ts">
/**
 * 插件组件侧挂区（设计稿 `.widget-col` + `widgetColHtml()`）
 * ========================================================
 *
 * 唯一视觉来源 = `personal-workspace-ui/index.html`。结构逐字对应：
 * ```
 * <aside class="widget-col" id="widgetCol">
 *   <div class="wscroll">                        ← 滚动交给内层（外层自己 overflow-y:auto
 *     <div class="wcard" draggable="true"         的话，绝对定位的手柄会跟着滚出视野）
 *          data-wid="…">
 *       <span class="wgrip" title="拖动排序">…</span>
 *       {widgetBody(w)}
 *     </div>
 *     …
 *     <button class="widget-add">＋ 添加组件</button>
 *   </div>
 * </aside>
 * ```
 *
 * 五条硬对齐（都不是"看起来像"，是可核对的口径）：
 *  1. 挂件清单与内容 = 设计稿 `WIDGETS` + `widgetBody()`（见 `stores/widgetCol.ts` 与下方模板）；
 *  2. 拖拽 = 设计稿 `enableSort(wsc, '.wcard', widgetSortCb)`，
 *     容器是 **`.wscroll`**（不是 `.widget-col`）—— 设计稿明确记过这个坑：
 *     绑错层级会让 `insertBefore` 抛 `NotFoundError`，拖拽静默失效；
 *  3. 收起态 = `.widget-col.collapsed`：**保留 224px 并只露「＋ 添加组件」**
 *     （与 `.shell.cinema .widget-col` 的"彻底让位"是两件事，见 base.css 注释）；
 *  4. 折叠/展开宽度过渡走 `--mt-dur-nav`（设计稿 `.widget-col` 的 transition）；
 *  5. 手柄（`.rsh--widget`）是**容器的子节点**，行为由 `useShellLayout` 在挂载时绑，
 *     与原型 `mountHandles()` 同口径（见 `ColHandle.vue` 顶部注释）。
 *
 * 与原型的一处有意差异：原型把侧挂列写在函数里由 `refreshWidgetCol()` 重绘；
 * 这里用 Vue 模板（数据驱动），因此**不再需要**"重绘后重新 wireDrag"这一步 ——
 * 排序监听由 `useAutoSort` 在列表长度变化时自动重挂。
 */
import { computed, nextTick, ref, watch } from 'vue'

import ColHandle from '@/components/ColHandle.vue'
import PwIcon from '@/components/PwIcon.vue'
import { useAutoSort } from '@/composables/useListSort'
import { useShellLayout } from '@/composables/useShellLayout'
import { useWidgetColStore } from '@/stores/widgetCol'

const store = useWidgetColStore()
const shell = useShellLayout()

/** 滚动容器（= 排序容器；见文件头第 2 条） */
const wscroll = ref<HTMLElement | null>(null)
/** 只作为 `useAutoSort` 的"列表长度"信号源，不参与渲染 */
const visibleCount = computed(() => store.visible.length)

/** 设计稿 `WIDGETS.filter(w=>w.on)` */
const list = computed(() => store.visible)

/** 设计稿 widgetBody() 的静态数据（原型是写死在函数里的示意内容，无接口） */
const TODO_ITEMS = ['改完 train.py 的数据加载', '回复论文审稿意见', '整理本周笔记']

/* 排序落位：与设计稿 `widgetSortCb` 同一口径（只重排可见项，再写回原槽位）。
   `announce` 走壳层的静默播报（设计稿也是 announce，不弹可见提示）。 */
useAutoSort(wscroll, visibleCount, {
  itemSelector: '.wcard',
  mode: 'move',
  onReorder: (from, to) => {
    void store.reorderVisible(from, to)
    shell.announce(`组件顺序已调整，第 ${from + 1} 个移到第 ${to + 1} 位`)
  },
})

/** 「＋ 添加组件」：设计稿 `data-act="open-customize"` —— 打开自定义抽屉 */
const customizeOpen = ref(false)

/** 抽屉里的顺序视图（= 全量清单；抽屉里改顺序，列里当场跟着变） */
const drawerList = computed(() => store.items)

function toggleDrawer(): void {
  customizeOpen.value = !customizeOpen.value
}

/** 打开的所有挂件都关掉后给出兜底提示（设计稿里不会发生，这里防"整列空白"） */
watch(
  () => store.visible.length,
  async (n) => {
    await nextTick()
    if (n === 0 && !store.collapsed) shell.announce('侧挂区没有启用任何组件')
  },
)
</script>

<template>
  <!--
    双类名：`app-widget` 是工程钩子（验收脚本 / querySelector / 挤压链测宽），
    `widget-col` 让设计稿的 `.widget-col` / `.widget-col.collapsed` /
    `.shell[data-cw="sm"] .widget-col` / `.shell[data-rs="*"] .widget-col` /
    `.shell.cinema .widget-col` 规则逐字生效。
  -->
  <aside
    class="app-widget widget-col"
    :class="{ collapsed: shell.widgetCollapsed.value }"
    aria-label="插件组件区"
  >
    <!-- 右缘手柄：拖动调整组件区宽度（本列左边界固定 → dir:-1） -->
    <ColHandle panel="widget" name="组件区" />

    <div ref="wscroll" class="wscroll">
      <!-- 挂件卡：draggable=true 与 .wgrip 均来自设计稿 widgetColHtml() -->
      <div
        v-for="w in list"
        :key="w.id"
        class="wcard"
        draggable="true"
        :data-wid="w.id"
      >
        <span class="wgrip" title="拖动排序"><PwIcon name="grip" :size="13" /></span>

        <!-- ---- 设计稿 widgetBody(w) 逐条 ---- -->

        <!-- weather -->
        <template v-if="w.id === 'weather'">
          <div class="row" style="justify-content: space-between">
            <span class="t-cap">天气</span><PwIcon name="cloud" :size="15" />
          </div>
          <div class="row" style="align-items: baseline; gap: var(--space-2); margin-top: 2px">
            <span class="t-num wcard-weather-temp">28°</span><span class="t-sm c2">多云</span>
          </div>
          <div class="t-cap">武汉</div>
        </template>

        <!-- todo -->
        <template v-else-if="w.id === 'todo'">
          <div class="row" style="justify-content: space-between">
            <span class="t-cap">待办</span><PwIcon name="check-c" :size="15" />
          </div>
          <div class="stack wcard-todo-list">
            <div v-for="(t, i) in TODO_ITEMS" :key="t" class="row wcard-todo-row">
              <span class="checkbox wcard-todo-box" :class="{ on: i === 0 }">
                <PwIcon name="check" :size="9" />
              </span>
              <span class="t-cap" :class="i === 0 ? 'wcard-todo-done' : 'c2'">{{ t }}</span>
            </div>
          </div>
        </template>

        <!-- music -->
        <template v-else-if="w.id === 'music'">
          <div class="row" style="justify-content: space-between">
            <span class="t-cap">正在播放</span><PwIcon name="music" :size="15" />
          </div>
          <div class="t-sm wcard-music-title">夜空中最亮的星</div>
          <div class="progress thin wcard-music-progress"><i style="width: 38%"></i></div>
        </template>

        <!-- clip -->
        <template v-else-if="w.id === 'clip'">
          <div class="row" style="justify-content: space-between">
            <span class="t-cap">剪贴板</span><PwIcon name="copy" :size="15" />
          </div>
          <div class="t-cap c2 wcard-clip-empty">还没有复制内容</div>
        </template>

        <!-- clock -->
        <template v-else-if="w.id === 'clock'">
          <div class="row" style="justify-content: space-between">
            <span class="t-cap">专注</span><PwIcon name="clock" :size="15" />
          </div>
          <div class="t-num wcard-focus-time">25:00</div>
          <button class="btn btn--secondary btn--sm wcard-focus-btn">开始专注</button>
        </template>

        <!-- 兜底：清单里出现设计稿没有的 id（不该发生，merge() 已过滤） -->
        <template v-else>
          <div class="t-cap">{{ w.name }}</div>
        </template>
      </div>

      <button class="widget-add" data-act="open-customize" @click="toggleDrawer">
        <PwIcon name="plus" :size="15" /> 添加组件
      </button>
    </div>

    <!-- 自定义抽屉：设计稿 `data-act="open-customize"` 的落点。
         结构与动效**全部复用设计稿的 `.drawer`**（右侧固定面板 + `drawerIn`），
         不另造一套浮层，也不再自造 @keyframes（`verify_tech05c` T4d 冻结了
         "@keyframes 全局只在 base.css 一处"，自造会在那里红灯）。 -->
    <template v-if="customizeOpen">
      <div class="scrim" @click="toggleDrawer"></div>
      <aside class="drawer" aria-label="自定义组件">
        <div class="drawer-head row">
          <span class="t-card drawer-title">自定义组件</span>
          <button class="icon-btn sm" title="关闭" @click="toggleDrawer">
            <PwIcon name="x" :size="14" />
          </button>
        </div>
        <div class="drawer-body">
          <div class="stack widget-customize-list">
            <button
              v-for="w in drawerList"
              :key="w.id"
              class="row widget-customize-item"
              :class="{ on: w.on }"
              @click="store.toggle(w.id)"
            >
              <span class="checkbox" :class="{ on: w.on }"><PwIcon name="check" :size="9" /></span>
              <PwIcon :name="w.icon" :size="15" />
              <span class="t-sm widget-customize-name">{{ w.name }}</span>
              <span class="t-cap">{{ w.on ? '已启用' : '已关闭' }}</span>
            </button>
          </div>
        </div>
        <div class="drawer-foot">
          <span class="t-cap">顺序按「拖动排序」调整；本列顺序与首页卡片网格是两份配置。</span>
        </div>
      </aside>
    </template>
  </aside>
</template>

<style scoped>
/* 本组件只放**设计稿没有**的三样东西：
 *   1) 挂件正文里那些原型的 inline style（原型写在 html 字符串里，这里没地方写 inline）；
 *   2) 「自定义抽屉」列表项的样式（抽屉外壳/头/体/脚全部来自设计稿 `.drawer*`）；
 *   3) 列表项的两态色（复用 token，不搬 class）。
 * 其余全部来自 base.css 的 `.widget-col` / `.wscroll` / `.wcard` / `.wgrip` / `.widget-add`。
 * 本文件**不含任何 @keyframes / animation / transition** —— 动效一律在 base.css。 */

/* ---- 1) widgetBody 里的 inline style（值与设计稿逐字一致） ---- */
.wcard-weather-temp {
  font-size: 20px;
}

.wcard-todo-list {
  gap: 5px;
  margin-top: var(--space-2);
}

.wcard-todo-row {
  gap: 6px;
}

.wcard-todo-box {
  width: 14px;
  height: 14px;
}

.wcard-todo-done {
  /* 设计稿：已完成项用 text-3 + 删除线（未完成项用 .c2） */
  color: var(--text-3);
  text-decoration: line-through;
}

.wcard-music-title {
  font-weight: 600;
  margin-top: 2px;
}

.wcard-music-progress {
  margin-top: var(--space-2);
}

.wcard-clip-empty {
  margin-top: 2px;
}

.wcard-focus-time {
  font-size: 20px;
  margin-top: 2px;
}

.wcard-focus-btn {
  margin-top: var(--space-2);
}

/* ---- 2) 自定义抽屉的列表项 ---- */
/* ⚠️ 不要用裸 `.grow`：设计稿里 `.grow` 永远是**上下文限定**的
 * （`.page-head .grow` / `.sec-head .grow` / `.hero .grow`），没有全局版。
 * 这里用自己命名的类承载同一条几何（flex:1;min-width:0），避免造一个设计稿不存在的工具类。 */
.drawer-title,
.widget-customize-name {
  flex: 1;
  min-width: 0;
}

.drawer-head {
  justify-content: space-between;
}

.widget-customize-list {
  gap: 2px;
}

.widget-customize-item {
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  border: none;
  background: transparent;
  border-radius: var(--r-md);
  color: var(--text-2);
  text-align: left;
}

.widget-customize-item:hover {
  background: var(--surface-3);
  color: var(--text-1);
}

.widget-customize-item.on {
  color: var(--text-1);
  font-weight: 600;
}
</style>
