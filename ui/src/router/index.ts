import { createRouter, createWebHistory, type Router } from 'vue-router'

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
  return createRouter({
    history: createWebHistory(),
    routes,
  })
}