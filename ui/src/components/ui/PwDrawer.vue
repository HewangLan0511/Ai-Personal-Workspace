<script setup lang="ts">
/**
 * PwDrawer —— 共享抽屉原语（TECH-05-C §P0）。
 *
 * 语义：右侧滑出的浮层（模型切换 / 添加模型 / 头像选择）。三段结构固定：
 *   head（标题 + 关闭）/ body（滚动区）/ foot（操作）
 *
 * ## 三个刻意的决定
 * 1. **Teleport 到 body**：抽屉是 `position: fixed`，若留在 `.app-shell` 的
 *    grid 内，任何祖先的 transform/filter 都会把它变成新的包含块而错位。
 * 2. **零 @keyframes**：进入/离开走 `.pw-fade-*` / `.pw-slide-*` 两组
 *    transition（TECH-04 T4c 把全局 keyframes 锁在 base.css 一处）。
 * 3. **Esc 由组件自己管**：原型 UI-07/UI-08 要求 Esc 取消编辑；把这件事
 *    放在原语里，后续页面不必各写一遍 keydown 监听（漏一处就行为不一致）。
 */
import { onUnmounted, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    ariaLabel?: string
  }>(),
  { ariaLabel: '' },
)

const emit = defineEmits<{ (e: 'close'): void }>()

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  }
}

watch(
  () => props.open,
  (open) => {
    if (typeof window === 'undefined') return
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
  { immediate: true },
)

onUnmounted(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="pw-fade">
      <div v-if="open" class="pw-scrim" @click="emit('close')"></div>
    </Transition>
    <Transition name="pw-slide">
      <aside
        v-if="open"
        class="pw-drawer"
        role="dialog"
        :aria-label="ariaLabel || title"
      >
        <div class="pw-drawer__head">
          <div class="pw-t-card pw-grow">{{ title }}</div>
          <button type="button" class="pw-btn pw-btn--icon" title="关闭" @click="emit('close')">
            ✕
          </button>
        </div>
        <div class="pw-drawer__body">
          <slot />
        </div>
        <div v-if="$slots.foot" class="pw-drawer__foot">
          <slot name="foot" />
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>
