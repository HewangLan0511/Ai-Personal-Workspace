<!-- 常用软件（阶段2 接入）：直接消费软件库排序（05 §4）—— 不在此重复实现排序 -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { useAppsStore } from '@/stores/apps'

const apps = useAppsStore()
const icons = ref<Record<string, string>>({})

/** 只显示前几个；顺序完全由 core 的 `AppsRepo::list` 决定（pinned → launch_count → last_used_at） */
const top = computed(() => apps.items.slice(0, 5))

onMounted(async () => {
  await apps.load()
  for (const a of top.value) {
    if (a.icon && !icons.value[a.icon]) {
      const url = await apps.loadIcon(a.icon)
      if (url) icons.value = { ...icons.value, [a.icon]: url }
    }
  }
})

async function open(id: number) {
  try {
    await apps.launch(id)
  } catch {
    // 失败提示由软件库页的 toast 承担；Widget 里静默，避免 Dashboard 弹提示打断
  }
}
</script>

<template>
  <div class="freq-apps">
    <p v-if="top.length === 0" class="empty-state">
      <span>软件库为空</span>
      <span class="stage-note">到「软件」页添加一个</span>
    </p>
    <button v-for="a in top" :key="a.id" type="button" class="freq-apps__row" @click.stop="open(a.id)">
      <img v-if="a.icon && icons[a.icon]" :src="icons[a.icon]" :alt="a.name" class="freq-apps__icon" />
      <span v-else class="freq-apps__icon freq-apps__icon--fallback">{{ a.name.slice(0, 1) }}</span>
      <span class="freq-apps__name" :title="a.path">{{ a.name }}</span>
      <span class="freq-apps__count">{{ a.launch_count }} 次</span>
    </button>
  </div>
</template>

<style scoped>
.freq-apps {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
}

.freq-apps__row {
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  background: transparent;
  border-color: transparent;
  padding: 4px 6px;
}

.freq-apps__icon {
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
}

.freq-apps__icon--fallback {
  display: grid;
  place-items: center;
  border-radius: 4px;
  background: var(--accent-weak);
  color: var(--accent);
  font-size: 12px;
}

.freq-apps__name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.freq-apps__count {
  color: var(--text-dim);
  font-size: 12px;
}
</style>
