<script setup lang="ts">
/**
 * PwChip —— 共享标签原语（TECH-05-C §P0）。
 *
 * 语义：一段**只读的短信息**（状态 / 来源 / 计数 / 标签）。
 * `removable` 时右侧带一个删除按钮（档案标签编辑用）。
 * `as="button"` 时根节点是 button —— 用于"可点的 chip"（工作模式模板、
 * 应用状态切换），避免在各页面重复写一遍 `chip` + `<button>`。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'brand' | 'outline'
    size?: 'sm' | 'md'
    /** 是否为可点击 chip（根节点渲染成 button）。 */
    as?: 'span' | 'button'
    /** 右侧删除按钮（档案标签）。 */
    removable?: boolean
    disabled?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'default', size: 'md', as: 'span', removable: false, disabled: false, type: 'button' },
)

const emit = defineEmits<{ (e: 'remove'): void }>()

const classes = computed(() => [
  'pw-chip',
  props.variant === 'default' ? '' : `pw-chip--${props.variant}`,
  props.size === 'sm' ? 'pw-chip--sm' : '',
  props.removable ? 'pw-chip--removable' : '',
])
</script>

<template>
  <component
    :is="as"
    :type="as === 'button' ? type : undefined"
    :disabled="as === 'button' ? disabled : undefined"
    :class="classes"
  >
    <slot />
    <button
      v-if="removable"
      type="button"
      class="pw-chip__x"
      title="删除"
      @click.stop="emit('remove')"
    >
      ✕
    </button>
  </component>
</template>
