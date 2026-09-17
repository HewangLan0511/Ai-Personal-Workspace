<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import WidgetCard from '@/components/WidgetCard.vue'
import WorkspaceStatus from '@/components/WorkspaceStatus.vue'
import { useWidgets } from '@/composables/useWidgets'
import { useWidgetStore } from '@/stores/widgets'
import { widgetRegistry } from '@/widgets'

const store = useWidgetStore()
const { moveUp, moveDown, toggleEnabled, recordUse } = useWidgets()
onMounted(() => store.load())

const list = computed(() => store.ordered)
const manageOpen = ref(false)

async function onUnlock() {
  await store.unlockLayout()
}
</script>

<template>
  <div class="dashboard">
    <header class="dashboard-bar">
      <h2>Dashboard</h2>
      <div class="dashboard-bar-actions">
        <span v-if="store.layoutLocked" class="stage-note">
          已按手动布局固定（不再自动调整尺寸）
        </span>
        <button v-if="store.layoutLocked" type="button" @click="onUnlock">
          恢复自动布局
        </button>
        <button type="button" @click="manageOpen = !manageOpen">
          {{ manageOpen ? '收起组件管理' : '组件管理' }}
        </button>
      </div>
    </header>

    <!-- TECH-05-C §P0-3：工作空间状态系统（UI-05-B）。
         数据全部来自 workspaceRuntime 门面；不启动真实软件、不控制窗口、不做真实恢复。
         它只加一个兄弟区块，不改动下面的组件管理 / 组件网格的节点身份（S2）。 -->
    <WorkspaceStatus />

    <!-- 组件管理：04 §3 enabled 字段的用户入口（REVIEW-003 L-016） -->
    <section v-if="manageOpen" class="widget-manage">
      <p class="hint">
        勾选控制显示；使用次数决定自动尺寸（≥3 中卡、≥10 大卡）。手动调序后布局固定，可点上方「恢复自动布局」解冻。
      </p>
      <ul>
        <li v-for="w in store.all" :key="w.id">
          <label>
            <input
              type="checkbox"
              :checked="w.enabled"
              @change="toggleEnabled(w.id)"
            />
            <span>{{ w.name }}</span>
            <span class="stage-note">使用 {{ store.usage[w.id] ?? 0 }} 次 · 当前 {{ w.size }}</span>
          </label>
        </li>
      </ul>
    </section>

    <div v-if="list.length === 0" class="empty-state">
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
        :use-count="store.usage[widget.id] ?? 0"
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
</template>
