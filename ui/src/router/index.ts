import { createRouter, createWebHistory, type Router } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
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
]

export function createAppRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes,
  })
}