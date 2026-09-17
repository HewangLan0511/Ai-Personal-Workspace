<script setup lang="ts">
/**
 * PwCard —— 共享卡片原语（TECH-05-C §P0）。
 *
 * 语义：一个内容容器（不是"一个可点的东西"）。变体对应原型 §5：
 *   default 白底细边 / ghost 次级表面
 * `stack` 打开竖排内距（模型卡这种"标题+状态+操作"的卡片）。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'ghost'
    size?: 'md' | 'lg'
    /** 悬停时抬起（列表里的可选卡片）。 */
    hoverable?: boolean
    /** 竖排 + 内距（模型卡）。 */
    stack?: boolean
    /** 桌面小组件里也要用：允许透传 role/aria 等。 */
    as?: 'div' | 'section' | 'article'
  }>(),
  { variant: 'default', size: 'md', hoverable: false, stack: false, as: 'div' },
)

const classes = computed(() => [
  'pw-card',
  props.variant === 'default' ? '' : `pw-card--${props.variant}`,
  props.size === 'lg' ? 'pw-card--lg' : '',
  props.hoverable ? 'pw-card--hoverable' : '',
  props.stack ? 'pw-card--stack' : '',
])
</script>

<template>
  <component :is="as" :class="classes">
    <slot />
  </component>
</template>
