<script setup lang="ts">
/**
 * UI-FUSION-REAL：首页 Hero（原型 .hero 当前工作大卡）。
 *
 * 数据来源唯一：`workspaceRuntime`（TECH-02 门面）—— 与 WorkspaceStatus 同一先例，
 * verify_tech02 T1c 登记在案（UI-FUSION-REAL 新增产品消费者）。
 * 只读展示：不启动软件、不控制窗口；「继续工作」= 路由跳转 /run（Run 壳自会如实投影）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { workspaceRuntime, type WorkspaceRuntime } from '@/workspace/runtime'

const router = useRouter()
const current = ref<WorkspaceRuntime | null>(null)
const apps = ref(workspaceRuntime.getApps())

function refresh(): void {
  current.value = workspaceRuntime.getCurrent()
  apps.value = workspaceRuntime.getApps()
}

let unsubscribe: (() => void) | null = null

onMounted(() => {
  refresh()
  unsubscribe = workspaceRuntime.subscribe(refresh)
})

onUnmounted(() => {
  unsubscribe?.()
  unsubscribe = null
})

const heroName = computed(() => current.value?.mode || '没有进行中的工作空间')
const heroCap = computed(() => {
  if (!current.value) return '当前工作空间 · 未启动'
  const goal = current.value.goal ? ` · ${current.value.goal}` : ''
  return `当前工作空间 · 已就绪${goal}`
})
const appNames = computed(() => apps.value.map((a) => a.name))
</script>

<template>
  <section class="hero">
    <div class="hero-main">
      <div class="pw-row hero-head">
        <span class="hero-badge">
          <svg class="hero-badge-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><use href="#i-ws" /></svg>
        </span>
        <div>
          <div class="pw-t-page">{{ heroName }}</div>
          <div class="pw-t-cap">{{ heroCap }}</div>
        </div>
      </div>
      <div class="pw-row hero-apps">
        <span v-for="name in appNames" :key="name" class="pw-chip pw-chip--sm">{{ name }}</span>
        <span v-if="!appNames.length" class="pw-t-cap">还没有应用在运行</span>
      </div>
      <div class="pw-row hero-actions">
        <button type="button" class="pw-btn pw-btn--primary pw-btn--lg" @click="router.push('/run')">
          继续工作
        </button>
        <button type="button" class="pw-btn pw-btn--secondary pw-btn--lg" @click="router.push('/mode')">
          切换工作空间
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* 原型 .hero：surface-1 大卡 + 右上 brand 径向光晕 + r-2xl */
.hero {
  position: relative;
  overflow: hidden;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-2xl);
  padding: var(--pad-card-lg);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  gap: var(--f-space-6);
  box-shadow: var(--shadow-sm);
}

.hero::after {
  content: '';
  position: absolute;
  right: -60px;
  top: -60px;
  width: 220px;
  height: 220px;
  border-radius: var(--r-full);
  background: radial-gradient(closest-side, var(--brand-50), transparent);
  opacity: 0.9;
  pointer-events: none;
}

.hero-main {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: var(--f-space-3);
}

.hero-head {
  gap: var(--f-space-3);
  align-items: center;
}

.hero-badge {
  width: 36px;
  height: 36px;
  border-radius: var(--r-lg);
  display: grid;
  place-items: center;
  background: var(--surface-3);
  border: 1px solid var(--border-subtle);
}

.hero-badge-ico {
  width: 19px;
  height: 19px;
  color: var(--brand-600);
}

.hero-apps {
  gap: var(--f-space-2);
  flex-wrap: wrap;
}

.hero-actions {
  gap: var(--f-space-3);
  margin-top: var(--f-space-2);
}

@media (max-width: 900px) {
  .hero {
    grid-template-columns: 1fr;
  }
}
</style>
