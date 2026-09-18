<script setup lang="ts">
/**
 * 侧边栏（设计稿 `.sidebar` + `navHtml()`）
 * ========================================
 *
 * 唯一视觉来源 = `personal-workspace-ui/index.html`。结构逐字对应：
 * ```
 * <aside class="sidebar">
 *   <div class="nav-group">…</div>            ← 分组与导航项**直接是 .sidebar 的子节点**
 *   <div class="nav-group">
 *     <div class="nav-group-title t-label">工作</div>
 *     <button class="nav-item active"><span class="ico">…</span><span class="lbl">…</span></button>
 *   </div>
 *   …
 *   <div class="nav-foot">
 *     <button class="nav-item">设置</button>
 *     <div class="device-line"><span class="ico">monitor</span><span class="txt">Windows PC · 在线</span></div>
 *   </div>
 * </aside>
 * ```
 *
 * 三条与"上一版实现"的**结构性**差异（都是为了让设计稿规则不再被覆盖）：
 *  1. **删掉 `.nav-list` 包裹层**：设计稿里 `.nav-group` 是 `.sidebar` 的直接子节点
 *     （`.sidebar` 自己就是 `display:flex;flex-direction:column`）。多一层 `.nav-list`
 *     只带来"多一个事实来源"，且 `.shell.mini .sidebar > *` 这类规则会错位。
 *  2. **删掉折叠按钮**：设计稿明确写过「主动折叠按钮已经删了，拖边界是唯一的展开途径」
 *     —— 收起/展开由右缘手柄（`.rsh--nav`，拖到底 + 蓄力）与窗口档位状态机驱动。
 *  3. **`.nav-foot` 不钉底、不加分隔线**：设计稿里 `.nav-foot` 没有任何 CSS 规则，
 *     就是紧跟分组之后的普通块。上一版的 `margin-top:auto + border-top` 是自造。
 *
 * 兼容约束（verify_stage1 / verify_tech05c / verify_tech05d）：
 *  - 容器保留 `.app-nav` 类（脚本按 `.app-nav a[href="/mode"]` 点按）；
 *  - 导航必须是**真实 `<a href>`**（RouterLink 渲染），不是 `data-act` 按钮；
 *  - 「布局」不进导航（原型 IA 无此项，/layout 路由保留，入口在模式页）。
 *
 * 折叠态 = 设计稿 `.shell.mini .sidebar`（图标 64px），由 `App.vue` 在壳层根上挂 `mini`；
 * 本文件因此**不再持有任何折叠样式**（上一版那套 `.app-nav.collapsed` 已删）。
 */
import { RouterLink } from 'vue-router'

import ColHandle from '@/components/ColHandle.vue'
import PwIcon from '@/components/PwIcon.vue'
import { connection } from '@/api/client'

interface NavEntry {
  to: string
  label: string
  /** 设计稿图标名（`PwIcon` 的 key） */
  icon: string
}

interface NavGroup {
  title?: string
  items: NavEntry[]
}

/** 与原型 `NAV` 一一对应；label 即原型原文。 */
const groups: NavGroup[] = [
  { items: [{ to: '/dashboard', label: '首页', icon: 'home' }] },
  {
    title: '工作',
    items: [
      { to: '/mode', label: '工作空间', icon: 'ws' },
      { to: '/software', label: '软件', icon: 'grid' },
    ],
  },
  { title: '学习', items: [{ to: '/learning', label: '学习', icon: 'book' }] },
  { title: '项目', items: [{ to: '/project', label: '项目', icon: 'folder' }] },
  { title: '生活', items: [{ to: '/life', label: '生活', icon: 'sun' }] },
  {
    items: [
      { to: '/ai', label: 'AI 助手', icon: 'sparkle' },
      { to: '/device', label: '设备', icon: 'monitor' },
      { to: '/profile', label: '档案', icon: 'card' },
      { to: '/plugins', label: '插件', icon: 'blocks' },
    ],
  },
]
</script>

<template>
  <aside class="app-nav sidebar">
    <!-- 右缘手柄：本列左边界固定 → dir:+1（向右拖变宽）。行为由 useShellLayout 挂。 -->
    <ColHandle panel="nav" name="侧边栏" />

    <!-- 设计稿 navHtml()：首页单独成组，其余按 group 标题分组 -->
    <div v-for="(g, gi) in groups" :key="gi" class="nav-group">
      <div v-if="g.title" class="nav-group-title t-label">{{ g.title }}</div>
      <RouterLink
        v-for="entry in g.items"
        :key="entry.to"
        :to="entry.to"
        class="nav-item"
        active-class="active"
        :title="entry.label"
      >
        <span class="ico"><PwIcon :name="entry.icon" :size="18" /></span>
        <span class="lbl">{{ entry.label }}</span>
      </RouterLink>
    </div>

    <!-- 设计稿 nav-foot：设置 + 设备行（无自造分隔线，见文件头第 3 条） -->
    <div class="nav-foot">
      <RouterLink to="/settings" class="nav-item" active-class="active" title="设置">
        <span class="ico"><PwIcon name="settings" :size="18" /></span>
        <span class="lbl">设置</span>
      </RouterLink>
      <div class="device-line" :title="connection.online ? 'Core 已连接' : 'Core 未连接'">
        <!-- 设计稿：device-line 的图标 = monitor，颜色 --success（收起态由 .shell.mini 隐藏文字） -->
        <span class="ico device-ico" :class="{ 'is-off': !connection.online }">
          <PwIcon name="monitor" :size="14" />
        </span>
        <span class="txt">Windows PC · {{ connection.online ? '在线' : '离线' }}</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* 本组件只放**设计稿没有**的三条：
 *   1) 导航是 `<a>`（原型是 `<button>`）→ 需要清掉下划线；
 *   2) `device-line` 的图标要跟随连接态变色（原型写死 --success）；
 *   3) 文字容器 `min-width:0` —— 设计稿的 `.lbl`/`.txt` 靠 max-width 收，flex 子项默认
 *      `min-width:auto` 会让 ellipsis 失效（原型是 flex 项直接就是 span，同款问题但它
 *      的 max-width 恰好够用；这里补一条以免长设备名把侧栏撑开）。
 * 其余（分组/项/active/foot/mini 态）全部来自 base.css 的设计稿规则。 */

.nav-item {
  text-decoration: none;
}

.ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.device-ico {
  color: var(--success);
}

.device-ico.is-off {
  color: var(--text-4);
}

.device-line .txt {
  min-width: 0;
}
</style>
