<!-- 学习路线进度（阶段6 接入真实数据） -->
<script setup lang="ts">
/**
 * Dashboard「学习路线」Widget。
 *
 * 数据来自 `learning` store（core 算好的进度，前端不自己数节点 —— 两侧各算一套必然不一致）。
 */
import { computed, onMounted } from 'vue'

import { useLearningStore } from '@/stores/learning'

const store = useLearningStore()
onMounted(() => void store.init())

const top = computed(() => store.goals.slice(0, 3))
</script>

<template>
  <div v-if="top.length === 0" class="empty-state">
    <span>尚无学习目标</span>
    <span class="stage-note">去「学习成长」页建一个目标，或用 AI 生成路线</span>
  </div>
  <ul v-else class="mini-goals">
    <li v-for="g in top" :key="g.id">
      <div class="line">
        <span class="g-title">{{ g.title }}</span>
        <span class="g-pct">{{ g.progress.percent }}%</span>
      </div>
      <div class="bar"><i :style="{ width: `${g.progress.percent}%` }" /></div>
      <span class="stage-note">{{ g.progress.done }}/{{ g.progress.total }} 个阶段</span>
    </li>
  </ul>
  <p v-if="store.activeReminders.length" class="remind-note">
    ⏰ {{ store.activeReminders.length }} 个目标长期未更新
  </p>
</template>

<style scoped>
.mini-goals {
  list-style: none;
  padding: 0;
  margin: 0;
}
.mini-goals li {
  margin-bottom: 10px;
}
.line {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.g-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.g-pct {
  opacity: 0.7;
  margin-left: 8px;
}
.bar {
  height: 5px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.08);
  overflow: hidden;
  margin: 4px 0 2px;
}
.bar i {
  display: block;
  height: 100%;
  background: #188038;
}
.remind-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: #b06000;
}
</style>
