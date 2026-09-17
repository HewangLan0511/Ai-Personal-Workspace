<!-- 当前项目（阶段6 接入真实数据；与工作模式联动） -->
<script setup lang="ts">
/**
 * Dashboard「当前项目」Widget（09 §6 联动）。
 *
 * **进入模式即显示当前项目** —— 数据源是 core 的 `/project/by-mode`，
 * 前端**不自己过滤**：多个项目绑同一模式时"选哪一个"由 core 决定
 * （优先未完成），两侧各写一套规则迟早不一致。
 *
 * 刷新靠 `MODE_CHANGED` 事件（不轮询）——模式切换是唯一的"当前项目会变"的时机。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { on } from '@/api/eventBridge'
import { projectApi, type Project } from '@/api/learningService'
import { modeApi } from '@/api/modeService'
import { logger } from '@/utils/logger'

const project = ref<Project | null>(null)
const modeName = ref<string | null>(null)
const loaded = ref(false)

/** `configured` 是"上次用过"（可能是任意 JSON），只有字符串才当模式名用。 */
async function refresh(): Promise<void> {
  try {
    const cur = await modeApi.current()
    const name = cur.running ?? (typeof cur.configured === 'string' ? cur.configured : null)
    modeName.value = name
    project.value = name ? await projectApi.byMode(name) : null
  } catch (e) {
    logger.warn('project', `读取当前项目失败：${String(e)}`)
  } finally {
    loaded.value = true
  }
}

let off: (() => void) | null = null

onMounted(() => {
  void refresh()
  off = on('MODE_CHANGED', () => void refresh())
})
onUnmounted(() => off?.())

const STATUS_LABEL: Record<Project['status'], string> = {
  ongoing: '进行中',
  paused: '已暂停',
  done: '已完成',
}

const statusText = computed(() => (project.value ? STATUS_LABEL[project.value.status] : ''))
</script>

<template>
  <div v-if="!loaded" class="stage-note">读取中…</div>

  <div v-else-if="!modeName" class="empty-state">
    <span>尚未进入工作模式</span>
    <span class="stage-note">进入模式后，这里会显示该模式绑定的项目</span>
  </div>

  <div v-else-if="!project" class="empty-state">
    <span>「{{ modeName }}」未绑定项目</span>
    <span class="stage-note">在「项目」页把项目关联到该模式</span>
  </div>

  <div v-else class="project-card">
    <div class="line">
      <span class="p-name">{{ project.name }}</span>
      <span class="p-status" :class="project.status">{{ statusText }}</span>
    </div>
    <p v-if="project.role" class="p-role">{{ project.role }}</p>
    <p v-if="project.techStack.length" class="p-tech">{{ project.techStack.join(' · ') }}</p>
    <p v-if="project.goalTitle" class="stage-note">关联目标：{{ project.goalTitle }}</p>
  </div>
</template>

<style scoped>
.project-card .line {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}
.p-name {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.p-status {
  flex: none;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.06);
}
.p-status.ongoing {
  color: #0b57d0;
  background: rgba(11, 87, 208, 0.1);
}
.p-status.done {
  color: #188038;
  background: rgba(24, 128, 56, 0.12);
}
.p-status.paused {
  color: #b06000;
  background: rgba(176, 96, 0, 0.12);
}
.p-role,
.p-tech {
  margin: 4px 0 0;
  font-size: 12px;
  opacity: 0.8;
}
</style>
