<script setup lang="ts">
/**
 * PwButton —— 共享按钮原语（TECH-05-C §P0）。
 *
 * 为什么需要它：真实应用此前没有按钮组件，各页面直接用裸 `<button>`，
 * 于是 base.css 的全局 button 样式（`background:var(--panel)` / 6px 圆角 /
 * `4px 10px` 内边距）在每处都要靠局部 CSS 覆盖一次。
 * 本组件把原型 §5 PRIMITIVES 的按钮语义补齐：5 个变体 × 3 个尺寸，
 * 值全部来自 tokens.css，形状与 base.css 的全局 button 明确分工
 * （`.pw-btn` 覆盖 padding/border/background）。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    /** 方形图标按钮（返回 / 关闭），不参与文字排版。 */
    icon?: boolean
    disabled?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'default', size: 'md', icon: false, disabled: false, type: 'button' },
)

const classes = computed(() => [
  'pw-btn',
  props.variant === 'default' ? '' : `pw-btn--${props.variant}`,
  props.size === 'md' ? '' : `pw-btn--${props.size}`,
  props.icon ? 'pw-btn--icon' : '',
])
</script>

<template>
  <button :type="type" :class="classes" :disabled="disabled">
    <slot />
  </button>
</template>
