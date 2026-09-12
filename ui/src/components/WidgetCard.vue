<script setup lang="ts">
import type { Widget } from '@/api/types'

const props = defineProps<{
  widget: Widget
  index: number
  total: number
  useCount: number
}>()

const emit = defineEmits<{
  (e: 'move-up', id: string): void
  (e: 'move-down', id: string): void
  (e: 'toggle-enabled', id: string): void
  (e: 'use', id: string): void
}>()

/** 卡片主体点击 = 一次「使用」，计入 04 §3 的使用次数统计。 */
function onBodyClick(): void {
  emit('use', props.widget.id)
}
</script>

<template>
  <article class="widget-card" :class="`size-${widget.size}`">
    <header class="widget-head">
      <span class="widget-title">
        {{ widget.name }}
        <span class="widget-usage" title="使用次数（决定自动尺寸）">{{ useCount }}</span>
      </span>
      <span class="widget-actions">
        <button
          type="button"
          :disabled="index <= 0"
          title="上移"
          @click.stop="emit('move-up', widget.id)"
        >▲</button>
        <button
          type="button"
          :disabled="index >= total - 1"
          title="下移"
          @click.stop="emit('move-down', widget.id)"
        >▼</button>
        <button type="button" title="隐藏此组件" @click.stop="emit('toggle-enabled', widget.id)">
          ✕
        </button>
      </span>
    </header>
    <section class="widget-body" @click="onBodyClick">
      <slot />
    </section>
  </article>
</template>
