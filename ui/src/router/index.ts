import { createRouter, createWebHistory, type Router } from 'vue-router'

import { inTauri } from '@/api/client'

/** 页面标题（原型 IA 的名称；窗口标题、document.title 与顶栏上下文都用它）。
 *  UI-FUSION 第四轮：导出给 TopBar 的 `.tb-context` 复用（同一份事实来源，
 *  避免"窗口标题"与"顶栏上下文"各写一张表而分叉）。 */
export const PAGE_TITLES: Record<string, string> = {
  dashboard: '首页',
  mode: '工作空间',
  software: '软件',
  learning: '学习',
  project: '项目',
  life: '生活',
  ai: 'AI 助手',
  profile: '档案',
  plugins: '插件',
  device: '设备',
  settings: '设置',
  models: '模型中心',
  run: '运行',
  layout: '布局',
  motion: '动效规范',
}

const APP_NAME = 'Personal Workspace'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
  },
  {
    path: '/software',
    name: 'software',
    component: () => import('@/views/SoftwareView.vue'),
  },
  {
    path: '/ai',
    name: 'ai',
    component: () => import('@/views/AiView.vue'),
  },
  {
    path: '/learning',
    name: 'learning',
    component: () => import('@/views/LearningView.vue'),
  },
  {
    path: '/project',
    name: 'project',
    component: () => import('@/views/ProjectView.vue'),
  },
  {
    path: '/mode',
    name: 'mode',
    component: () => import('@/views/ModeView.vue'),
  },
  {
    path: '/layout',
    name: 'layout',
    component: () => import('@/views/LayoutView.vue'),
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
  },
  {
    path: '/life',
    name: 'life',
    component: () => import('@/views/LifeView.vue'),
  },
  {
    path: '/device',
    name: 'device',
    component: () => import('@/views/DeviceView.vue'),
  },
  {
    path: '/plugins',
    name: 'plugins',
    component: () => import('@/views/PluginsView.vue'),
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
  },
  {
    // TECH-05-C §P0-1：模型管理中心（独立页）。
    // **不进主导航**（原型 UI-06 的定位：入口在「设置 → AI 与模型」，
    // 不抢 AI 助手的入口）；返回按钮按 `?from=ai|settings` 回到来源。
    path: '/models',
    name: 'models',
    component: () => import('@/views/ModelsView.vue'),
  },
  {
    // TECH-07-C C1：Run 页（工作空间运行壳）。
    // 原型 personal-workspace-ui 的整页缺口，本路由是 UI 融合第一个新整页。
    // 只做 UI 壳：顶栏/状态条/主舞台/软件栏/minimap/AI 侧栏入口；
    // 数据一律经 `@/workspace/runtime`（Workspace Runtime Adapter），禁止直连 @/api。
    path: '/run',
    name: 'run',
    component: () => import('@/views/RunView.vue'),
  },
  {
    // 动效规范（UI-FUSION 动效对接）：设计稿 `ROUTES.showcase` 页头写明
    // 「只做展示与切换，不进主导航 —— 主 IA 不动，入口放在设置 · 外观」，
    // 故本路由**不进侧边导航**，入口 = 设置页 · 外观 的「动效规范」那一行。
    // 内容 = 实时演示台 + 场景清单 + 三档降级对比（设计稿 showcase + guard 合并页）。
    path: '/motion',
    name: 'motion',
    component: () => import('@/views/MotionSpecView.vue'),
  },
  {
    // TECH-01 验证固件（dev-only，不进导航、不进产品 IA）
    path: '/dev/motion',
    name: 'dev-motion',
    component: () => import('@/views/DevMotionHarness.vue'),
  },
  {
    // TECH-02 Workspace Runtime 验证固件（dev-only，不进导航、不进产品 IA）
    path: '/dev/workspace',
    name: 'dev-workspace',
    component: () => import('@/views/DevWorkspaceHarness.vue'),
  },
]

export function createAppRouter(): Router {
  const router = createRouter({
    history: createWebHistory(),
    routes,
  })

  // 窗口标题跟随当前页面（桌面应用的基本行为；同时让"App 当前停在哪一页"
  // 成为可被外部工具读取的事实 —— 实机验收用 Win32 读窗口标题判定路由）。
  router.afterEach((to) => {
    const label = PAGE_TITLES[String(to.name ?? '')]
    const title = label ? `${label} · ${APP_NAME}` : APP_NAME
    if (typeof document !== 'undefined') document.title = title
    if (inTauri()) {
      void import('@tauri-apps/api/window')
        .then(({ getCurrentWindow }) => getCurrentWindow().setTitle(title))
        .catch(() => {})
    }
  })

  return router
}